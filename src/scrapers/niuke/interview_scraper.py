from __future__ import annotations

import random
import re
import time
from typing import Any
from urllib.parse import urlencode

from playwright.sync_api import Page, Response, sync_playwright

from src.config import Settings
from src.scrapers.niuke.auth import launch_niuke_persistent, load_niuke_config
from src.scrapers.niuke.interview_parser import parse_interview_post

INTERVIEW_LIST_BASE = "https://www.nowcoder.com/discuss?type=exp&order=newest"
POST_ID_PATTERN = re.compile(r"/discuss/(\d+)")


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


def check_login_required(page: Page) -> None:
    if "/login" in (page.url or "").lower():
        raise RuntimeError("需要登录")


def build_interview_list_url(
    *,
    company_id: str | None = None,
    page_num: int = 1,
) -> str:
    params: dict[str, str] = {"type": "exp", "order": "newest"}
    if company_id:
        params["companyId"] = company_id
    if page_num > 1:
        params["page"] = str(page_num)
    return f"https://www.nowcoder.com/discuss?{urlencode(params)}"


def extract_post_ids_from_payload(payload: dict[str, Any]) -> list[str]:
    ids: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key in ("id", "postId", "discussId", "entityId"):
                val = node.get(key)
                if val is not None and str(val).isdigit():
                    ids.append(str(val))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return list(dict.fromkeys(ids))


def extract_post_ids_from_page(page: Page) -> list[str]:
    ids: list[str] = []
    try:
        links = page.locator('a[href*="/discuss/"]')
        count = min(links.count(), 200)
        for i in range(count):
            href = links.nth(i).get_attribute("href") or ""
            match = POST_ID_PATTERN.search(href)
            if match:
                ids.append(match.group(1))
    except Exception:
        pass
    return list(dict.fromkeys(ids))


def collect_post_ids(page: Page) -> list[str]:
    api_ids: list[str] = []
    dom_ids: list[str] = []

    def on_response(response: Response) -> None:
        url = response.url
        if "discuss" not in url.lower():
            return
        payload = _safe_json_response(response)
        if payload:
            api_ids.extend(extract_post_ids_from_payload(payload))

    page.on("response", on_response)
    page.wait_for_timeout(1500)
    dom_ids = extract_post_ids_from_page(page)
    merged = list(dict.fromkeys(api_ids + dom_ids))
    return merged


class NiukeInterviewScraper:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        niuke_cfg = load_niuke_config()
        self.delay_ms = int(niuke_cfg.get("delay_ms", settings.delay_ms))
        self.headless = bool(niuke_cfg.get("headless", False))

    def scrape(
        self,
        company_id: str | None = None,
        max_pages: int = 5,
    ) -> list[dict]:
        records: list[dict] = []
        seen_post_ids: set[str] = set()

        with sync_playwright() as p:
            context = launch_niuke_persistent(p, headless=self.headless)
            list_page = context.pages[0] if context.pages else context.new_page()

            for page_num in range(1, max_pages + 1):
                url = build_interview_list_url(
                    company_id=company_id,
                    page_num=page_num,
                )
                list_page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                check_login_required(list_page)
                _random_delay(self.delay_ms)

                post_ids = collect_post_ids(list_page)
                for post_id in post_ids:
                    if post_id in seen_post_ids:
                        continue
                    seen_post_ids.add(post_id)

                    detail_page = context.new_page()
                    try:
                        detail_url = f"https://www.nowcoder.com/discuss/{post_id}"
                        detail_page.goto(
                            detail_url,
                            wait_until="domcontentloaded",
                            timeout=45_000,
                        )
                        check_login_required(detail_page)
                        record = parse_interview_post(detail_page)
                        if record.get("post_id"):
                            records.append(record)
                    finally:
                        detail_page.close()
                    _random_delay(self.delay_ms)

                if page_num < max_pages:
                    _random_delay(self.delay_ms)

            context.close()

        return records
