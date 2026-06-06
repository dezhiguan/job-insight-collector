from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import BrowserContext, Page, Response, sync_playwright

from src.auth import is_logged_in, verify_login
from src.browser import CDP_PORT, connect_cdp, is_cdp_up, launch_persistent
from src.config import Settings
from src.exporter import JobExporter
from src.scrapers.boss.parser import (
    normalize_job,
    parse_detail_payload,
    parse_joblist_payload,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _random_delay(delay_ms: int) -> None:
    low = max(500, delay_ms)
    high = max(low + 500, delay_ms * 2)
    time.sleep(random.uniform(low, high) / 1000.0)


def _safe_json_response(response: Response) -> dict[str, Any] | None:
    try:
        if response.status != 200:
            return None
        content_type = response.headers.get("content-type", "")
        if "json" not in content_type and "javascript" not in content_type:
            return None
        return response.json()
    except Exception:
        return None


def _job_id_from_item(item: dict[str, Any]) -> str:
    for key in ("encryptJobId", "jobId", "encryptId", "jid"):
        val = item.get(key)
        if val:
            return str(val)
    return ""


class JobScraper:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.failed_ids: list[str] = []
        self._list_cache: dict[str, dict[str, Any]] = {}
        self.require_login = True

    def _ensure_login(self) -> None:
        from src.browser import USER_DATA_DIR

        if not USER_DATA_DIR.exists() and not self.settings.storage_state_path.exists():
            raise FileNotFoundError(
                "未找到登录态，请先运行: ./run.sh login"
            )
        if not verify_login(headless=True):
            raise RuntimeError(
                "登录态已失效，请重新运行: ./run.sh login"
            )

    def _attach_list_listener(self, page: Page) -> None:
        def on_response(response: Response) -> None:
            url = response.url
            if "joblist.json" not in url and "job/list" not in url:
                return
            payload = _safe_json_response(response)
            if not payload:
                return
            for item in parse_joblist_payload(payload):
                jid = _job_id_from_item(item)
                if jid:
                    self._list_cache[jid] = item

        page.on("response", on_response)

    def _collect_list_pages(self, page: Page) -> list[dict[str, Any]]:
        page.goto(
            self.settings.search_url,
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        _random_delay(self.settings.delay_ms)

        if not is_logged_in(page) and "login" in page.url.lower():
            if self.require_login:
                raise RuntimeError("需要登录，请运行 ./run.sh login")
            print("提示: 当前未登录，仅采集公开列表数据（详情可能不完整）。")

        collected_pages = 0
        last_count = 0
        stagnant_rounds = 0

        while collected_pages < self.settings.max_pages:
            # scroll to trigger infinite load / next page API
            for _ in range(3):
                page.mouse.wheel(0, 2000)
                time.sleep(1.2)

            _random_delay(self.settings.delay_ms)
            current = len(self._list_cache)
            if current == last_count:
                stagnant_rounds += 1
            else:
                stagnant_rounds = 0
            last_count = current
            collected_pages += 1

            if stagnant_rounds >= 2:
                break

        return list(self._list_cache.values())

    def _fetch_detail_via_api(
        self, context: BrowserContext, item: dict[str, Any], retries: int = 2
    ) -> dict[str, Any] | None:
        job_id = _job_id_from_item(item)
        if not job_id:
            return None
        security_id = item.get("securityId") or item.get("secId") or ""
        detail_url = (
            f"https://www.zhipin.com/job_detail/{job_id}.html"
            f"?securityId={security_id}" if security_id
            else f"https://www.zhipin.com/job_detail/{job_id}.html"
        )

        detail_payload: dict[str, Any] | None = None

        for attempt in range(retries + 1):
            page = context.new_page()
            captured: dict[str, Any] | None = None

            def on_response(response: Response) -> None:
                nonlocal captured
                if captured is not None:
                    return
                url = response.url
                if "job/detail.json" not in url and "job/detail" not in url:
                    return
                parsed = urlparse(url)
                qs = parse_qs(parsed.query)
                resp_job = (qs.get("jobId") or qs.get("encryptJobId") or [""])[0]
                if resp_job and resp_job != job_id:
                    return
                payload = _safe_json_response(response)
                if payload and payload.get("code") in (0, None):
                    zp = payload.get("zpData") or payload
                    if zp:
                        captured = parse_detail_payload(payload)

            page.on("response", on_response)
            try:
                page.goto(detail_url, wait_until="domcontentloaded", timeout=45_000)
                _random_delay(self.settings.delay_ms)
                if captured:
                    detail_payload = captured
                    break
                # fallback: parse embedded JSON from HTML
                html = page.content()
                detail_payload = _extract_detail_from_html(html)
                if detail_payload and _has_description(detail_payload):
                    break
            except Exception:
                if attempt < retries:
                    _random_delay(self.settings.delay_ms * (attempt + 2))
            finally:
                page.close()

        return detail_payload

    def scrape(self, *, require_login: bool = True) -> Path:
        self.require_login = require_login
        if require_login:
            self._ensure_login()
        exporter = JobExporter(self.settings.data_dir)
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)

        use_cdp = is_cdp_up(CDP_PORT)
        with sync_playwright() as p:
            if use_cdp:
                print("连接本机 Chrome（CDP 模式）进行采集…")
                browser, context = connect_cdp(p, CDP_PORT)
            else:
                print("使用持久化内置浏览器进行采集…")
                browser = None
                context = launch_persistent(p, headless=self.settings.headless)

            list_page = context.pages[0] if context.pages else context.new_page()
            self._attach_list_listener(list_page)
            items = self._collect_list_pages(list_page)

            print(f"列表共发现 {len(items)} 个职位，开始抓取详情…")

            for idx, item in enumerate(items, start=1):
                job_id = _job_id_from_item(item)
                if not job_id:
                    continue
                print(f"[{idx}/{len(items)}] 抓取 {job_id} …")
                detail = self._fetch_detail_via_api(context, item)
                record = normalize_job(item, detail, job_id=job_id)
                if not record.get("job_description"):
                    self.failed_ids.append(job_id)
                    print(f"  警告: {job_id} 未获取到 job_description")
                else:
                    exporter.append(record)
                    print(f"  已写入: {record.get('job_title', '')}")

            if browser is not None:
                browser.close()  # disconnect CDP; leave user's Chrome open
            else:
                context.close()

        failed_path = PROJECT_ROOT / "failed_ids.txt"
        if self.failed_ids:
            failed_path.write_text("\n".join(self.failed_ids) + "\n", encoding="utf-8")
            print(f"失败 job_id 已写入 {failed_path}")

        print(
            f"完成: 新增 {exporter.written} 条, 跳过重复 {exporter.skipped} 条, "
            f"输出 {exporter.jsonl_path}"
        )
        return exporter.jsonl_path


def _has_description(data: dict[str, Any]) -> bool:
    if data.get("postDescription") or data.get("jobDesc"):
        return True
    job_info = data.get("jobInfo")
    if isinstance(job_info, dict):
        return bool(job_info.get("postDescription") or job_info.get("jobDesc"))
    return False


def _extract_detail_from_html(html: str) -> dict[str, Any] | None:
    patterns = [
        r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*;?\s*</script>",
        r'"postDescription"\s*:\s*"((?:\\.|[^"\\])*)"',
    ]
    for pattern in patterns[:1]:
        match = re.search(pattern, html, re.DOTALL)
        if not match:
            continue
        try:
            data = json.loads(match.group(1))
            if isinstance(data, dict):
                return parse_detail_payload(data) if "zpData" in data else data
        except json.JSONDecodeError:
            continue

    # smaller fallback: find jobInfo block
    m = re.search(r'"jobInfo"\s*:\s*(\{[^}]+\})', html)
    if m:
        try:
            job_info = json.loads(m.group(1))
            return {"jobInfo": job_info}
        except json.JSONDecodeError:
            pass
    return None
