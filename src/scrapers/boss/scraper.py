from __future__ import annotations

import asyncio
import json as _json_mod
import random
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright

from src.auth import is_logged_in
from src.browser import (
    CDP_PORT,
    connect_cdp,
    is_cdp_up,
    launch_persistent,
    launch_with_storage_state,
)
from src.config import Settings
from src.exporter import JobExporter
from src.scrapers.boss.parser import (
    normalize_job,
    parse_joblist_payload,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

_JOBLIST_URL = "https://www.zhipin.com/wapi/zpgeek/search/joblist.json"

# Human-like reading delays: 20–45 s between jobs
_DETAIL_DELAY_LOW_S = 20
_DETAIL_DELAY_HIGH_S = 45


def _human_delay() -> None:
    """Pause like a person skimming a job posting."""
    time.sleep(random.uniform(_DETAIL_DELAY_LOW_S, _DETAIL_DELAY_HIGH_S))


def _random_delay(delay_ms: int) -> None:
    low = max(500, delay_ms)
    high = max(low + 500, delay_ms * 2)
    time.sleep(random.uniform(low, high) / 1000.0)


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
        self.require_login = True

    def _ensure_login(self) -> None:
        from src.browser import USER_DATA_DIR

        has_profile = USER_DATA_DIR.exists()
        has_storage_state = self.settings.storage_state_path.exists()
        if not has_profile and not has_storage_state:
            raise FileNotFoundError(
                "未找到登录态，请先运行: ./run.sh login"
            )

    def _browser_fetch(
        self, page: Page, endpoint: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Call a Boss API via the browser's native fetch (real cookies, low call count)."""
        try:
            return page.evaluate(
                """async ([url, params]) => {
                    const qs = new URLSearchParams(params);
                    const resp = await fetch(url + '?' + qs, {
                        credentials: 'include',
                        headers: {'Accept': 'application/json, text/plain, */*'}
                    });
                    return await resp.json();
                }""",
                [endpoint, {str(k): str(v) for k, v in params.items()}],
            )
        except Exception as e:
            return {"code": -1, "message": str(e)}

    def _ensure_boss_page(self, page: Page) -> None:
        """Make sure the page is on Boss直聘 (navigate if not)."""
        if "zhipin.com" not in (page.url or ""):
            page.goto(
                "https://www.zhipin.com/web/geek/job",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            time.sleep(2)
        if not is_logged_in(page) and "login" in page.url.lower():
            if self.require_login:
                raise RuntimeError("需要登录，请运行 ./run.sh login")

    def _ensure_stable_boss_page(self, page: Page) -> None:
        """Navigate to a stable Boss page (home/city) suitable for fetch() calls.

        Avoids the SPA search page whose Vue router can trigger mid-navigation
        redirects that kill evaluate() calls.
        """
        current = page.url or ""
        # Use guangzhou city page — static, stable, no Vue re-init
        if "zhipin.com" not in current or "passport" in current or "verify" in current:
            try:
                page.goto("https://www.zhipin.com/guangzhou/",
                          wait_until="domcontentloaded", timeout=30_000)
            except Exception:
                pass
        # Wait for any pending navigation to settle
        try:
            page.wait_for_load_state("domcontentloaded", timeout=8_000)
        except Exception:
            pass
        time.sleep(2)
        if not is_logged_in(page) and "login" in (page.url or "").lower():
            if self.require_login:
                raise RuntimeError("需要登录，请运行 ./run.sh login")

    def _collect_jobs_via_fetch(
        self,
        page: Page,
        extra_keywords: list[str] | None = None,
        skip_ids: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Collect job list via browser fetch across multiple keywords.

        All API calls are made upfront before any detail-page navigation so that
        detail-page navigations don't exhaust the rate-limit quota for list calls.
        """
        self._ensure_stable_boss_page(page)

        keywords = [self.settings.keyword]
        if extra_keywords:
            keywords += [k for k in extra_keywords if k not in keywords]

        seen: dict[str, dict[str, Any]] = {}

        for kw in keywords:
            print(f"  关键词 {kw!r}:")
            for page_num in range(1, self.settings.max_pages + 1):
                params = {
                    "scene": "1",
                    "query": kw,
                    "city": self.settings.city,
                    "experience": "", "degree": "", "industry": "",
                    "scale": "", "stage": "", "position": "",
                    "salary": "", "multiBusinessDistrict": "",
                    "page": str(page_num),
                    "pageSize": "20",
                    "sortType": "1",
                }
                payload = self._browser_fetch(page, _JOBLIST_URL, params)
                code = payload.get("code")

                if code == 37 or code == 36:
                    print(f"    第 {page_num} 页被限速 (code={code})，等待后重试…")
                    time.sleep(random.uniform(10, 20))
                    payload = self._browser_fetch(page, _JOBLIST_URL, params)
                    code = payload.get("code")

                if code != 0:
                    print(f"    第 {page_num} 页异常 code={code} msg={payload.get('message')}")
                    break

                jobs = parse_joblist_payload(payload)
                if not jobs:
                    break

                new_count = 0
                for item in jobs:
                    jid = _job_id_from_item(item)
                    if jid and jid not in seen and (skip_ids is None or jid not in skip_ids):
                        seen[jid] = item
                        new_count += 1

                print(f"    第 {page_num} 页: {len(jobs)} 个职位, 新增 {new_count} (累计去重 {len(seen)})")
                if not jobs:
                    break
                # Human-like pause between list pages
                time.sleep(random.uniform(4, 8))

            # Pause between keywords
            time.sleep(random.uniform(5, 10))

        return list(seen.values())

    def _wait_for_captcha_clear(self, page: Page) -> bool:
        """Pause and ask user to solve CAPTCHA in browser. Returns True if cleared."""
        import select, sys
        print()
        print("=" * 60)
        print("⚠  Boss直聘 要求验证，请在浏览器中完成验证码")
        print("   完成后回到此终端按 Enter 继续，或等待 120 秒自动继续")
        print("=" * 60)
        stdin_ok = sys.stdin is not None and sys.stdin.isatty()
        deadline = time.time() + 120
        while time.time() < deadline:
            if stdin_ok:
                try:
                    ready, _, _ = select.select([sys.stdin], [], [], 2.0)
                    if ready:
                        sys.stdin.readline()
                        break
                except (OSError, ValueError):
                    time.sleep(2)
            else:
                time.sleep(2)
        current = page.url or ""
        cleared = "verify" not in current and "/passport/" not in current
        print("验证已通过，继续采集…" if cleared else "仍在验证页，将跳过此职位")
        return cleared

    def _fetch_detail_via_page(
        self, page: Page, item: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Navigate to the job detail page and extract description from the rendered DOM.

        This is the human-like path: real page navigation → Boss JS runs →
        description appears in DOM → we read it. No extra API calls.
        """
        job_id = _job_id_from_item(item)
        if not job_id:
            return None
        security_id = item.get("securityId") or item.get("secId") or ""

        detail_url = f"https://www.zhipin.com/job_detail/{job_id}.html"
        if security_id:
            detail_url += f"?securityId={security_id}"

        for attempt in range(2):
            try:
                # domcontentloaded fires before Boss's JS redirect runs.
                # The SSR HTML already has the description in the DOM at this point.
                page.goto(detail_url, wait_until="domcontentloaded", timeout=45_000)
            except Exception:
                return None

            current_url = page.url
            if "verify" in current_url or "/passport/" in current_url:
                cleared = self._wait_for_captcha_clear(page)
                if not cleared:
                    return None
                # After clearing CAPTCHA, navigate to the job page again
                try:
                    page.goto(detail_url, wait_until="domcontentloaded", timeout=45_000)
                except Exception:
                    return None
                current_url = page.url
                if "verify" in current_url or "/passport/" in current_url:
                    return None

            if "job_detail" not in current_url:
                # Redirected before domcontentloaded (rare); retry once
                if attempt == 0:
                    time.sleep(random.uniform(2, 4))
                    continue
                return None

            # Extract immediately — before Boss JS can fire the redirect
            try:
                result: dict[str, Any] | None = page.evaluate("""() => {
                    function getText(sels) {
                        for (const s of sels) {
                            const el = document.querySelector(s);
                            const t = el && (el.innerText || el.textContent || '').trim();
                            if (t) return t;
                        }
                        return '';
                    }

                    // Description
                    const descSels = [
                        '.job-sec-text',
                        '.job-detail-section .job-sec-text',
                        '.job-sec .job-sec-text',
                        '[class*="sec-text"]',
                    ];
                    let desc = '';
                    for (const s of descSels) {
                        const el = document.querySelector(s);
                        const t = el && (el.innerText || '').trim();
                        if (t && t.length > 30) { desc = t; break; }
                    }

                    // Job title
                    const title = getText([
                        '.job-name', 'h1.name', '.position-name', 'h1',
                    ]);

                    // Salary
                    const salary = getText([
                        '.salary', '.job-salary', '[class*="salary"]',
                    ]);

                    // Company
                    const company = getText([
                        '.company-name', '.brand-name', '[class*="company-name"]',
                    ]);

                    // Experience / degree tags
                    const tags = getText([
                        '.job-qualifications', '.tag-list', '[class*="requirement"]',
                    ]);

                    // Publish time
                    const publishTime = getText([
                        '[class*="job-time"]', '[class*="update-time"]',
                        '[class*="publish-time"]', '.date', '[class*="date"]',
                    ]);

                    // Fallback: window.__INITIAL_STATE__
                    let statePublishTime = '';
                    if (!desc || !publishTime) {
                        try {
                            const st = window.__INITIAL_STATE__;
                            if (st) {
                                const zp = st.zpData || st;
                                const ji = zp.jobInfo || {};
                                const d = ji.postDescription || ji.jobDesc || '';
                                if (d && d.length > 10 && !desc) desc = d;
                                const pt = ji.publishTime || ji.lastModifyTime || ji.updateTime || '';
                                if (pt) statePublishTime = String(pt);
                            }
                        } catch(e) {}
                    }

                    if (!desc) return null;
                    return {postDescription: desc, jobName: title, salaryDesc: salary, brandName: company, tagText: tags, publishTime: publishTime || statePublishTime};
                }""")
                if result:
                    return result
                # Description not in DOM yet; retry once
                if attempt == 0:
                    time.sleep(2)
                    continue
                return None
            except Exception:
                if attempt == 0:
                    time.sleep(2)
                    continue
                return None

        return None

    # ── 原生 CDP WebSocket 路径（绕过 Playwright connect_over_cdp） ──────────

    def _cdp_fetch(self, endpoint: str, params: dict) -> dict:
        """用原生 CDP WebSocket 在用户真实 Chrome 里执行 fetch，返回 JSON。"""
        import httpx as _httpx
        import websockets as _ws

        async def _run():
            version = _httpx.get("http://127.0.0.1:9222/json/version").json()
            browser_ws = version["webSocketDebuggerUrl"]

            async with _ws.connect(browser_ws, max_size=10_000_000) as bws:
                # 找 zhipin.com page target
                await bws.send(_json_mod.dumps({"id": 1, "method": "Target.getTargets"}))
                resp = _json_mod.loads(await bws.recv())
                targets = resp.get("result", {}).get("targetInfos", [])
                page_target = next(
                    (t for t in targets
                     if t.get("type") == "page" and "zhipin.com" in t.get("url", "")),
                    None,
                )
                if not page_target:
                    return {"code": -1, "message": "未找到 zhipin.com 标签"}

                tid = page_target["targetId"]
                await bws.send(_json_mod.dumps({
                    "id": 2, "method": "Target.attachToTarget",
                    "params": {"targetId": tid, "flatten": True},
                }))
                attach_resp = _json_mod.loads(await bws.recv())
                session_id = attach_resp.get("result", {}).get("sessionId", "")

            # 用 sessionId 在 target session 里执行 fetch
            target_ws = f"ws://127.0.0.1:9222/devtools/page/{tid}"
            qs = "&".join(f"{k}={v}" for k, v in params.items())
            url_with_qs = f"{endpoint}?{qs}"
            js = f"""(async () => {{
                const r = await fetch({_json_mod.dumps(url_with_qs)}, {{
                    credentials: 'include',
                    headers: {{'Accept': 'application/json, text/plain, */*'}}
                }});
                return await r.json();
            }})()"""

            async with _ws.connect(target_ws, max_size=10_000_000) as tws:
                await tws.send(_json_mod.dumps({
                    "id": 10, "method": "Runtime.evaluate",
                    "params": {"expression": js, "awaitPromise": True, "returnByValue": True},
                }))
                # 消耗事件直到拿到 id=10 的回复
                for _ in range(30):
                    raw = await tws.recv()
                    msg = _json_mod.loads(raw)
                    if msg.get("id") == 10:
                        result = msg.get("result", {}).get("result", {})
                        return result.get("value", {"code": -1, "message": "no value"})
                return {"code": -1, "message": "timeout"}

        return asyncio.run(_run())

    def _cdp_fetch_detail(self, job_id: str, security_id: str) -> dict | None:
        """用 CDP 在真实 Chrome 里访问详情页，提取 publishTime + postDescription。"""
        import httpx as _httpx
        import websockets as _ws

        detail_url = f"https://www.zhipin.com/job_detail/{job_id}.html"
        if security_id:
            detail_url += f"?securityId={security_id}"

        JS_EXTRACT = """(() => {
            const descSels = ['.job-sec-text','.job-detail-section .job-sec-text',
                              '.job-sec .job-sec-text','[class*="sec-text"]'];
            let desc = '';
            for (const s of descSels) {
                const el = document.querySelector(s);
                const t = el && (el.innerText || '').trim();
                if (t && t.length > 30) { desc = t; break; }
            }

            // 1. JSON-LD 结构化数据里的 upDate
            let publishTime = '';
            try {
                const ldScripts = document.querySelectorAll('script[type="application/ld+json"]');
                for (const s of ldScripts) {
                    const data = JSON.parse(s.textContent || '{}');
                    const d = data.upDate || data.dateModified || data.datePublished || '';
                    if (d) { publishTime = d.slice(0, 10); break; }
                }
            } catch(e) {}

            // 2. 页面可见的 "页面更新时间：XXXX-XX-XX"
            if (!publishTime) {
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                while(walker.nextNode()) {
                    const t = walker.currentNode.nodeValue.trim();
                    const m = t.match(/页面更新时间[：:]\s*(\d{4}-\d{2}-\d{2})/);
                    if (m) { publishTime = m[1]; break; }
                }
            }

            // 3. __INITIAL_STATE__ fallback
            let stateDesc = '', statePublishTime = '';
            try {
                const st = window.__INITIAL_STATE__;
                if (st) {
                    const ji = (st.zpData || st).jobInfo || {};
                    if (!desc) stateDesc = ji.postDescription || ji.jobDesc || '';
                    const rawPt = ji.publishTime || ji.lastModifyTime || ji.updateTime || ji.activeTime || '';
                    if (rawPt) {
                        // 时间戳转日期字符串
                        const n = Number(rawPt);
                        if (n > 1000000000) {
                            statePublishTime = new Date(n * 1000).toISOString().slice(0, 10);
                        } else {
                            statePublishTime = String(rawPt).slice(0, 10);
                        }
                    }
                }
            } catch(e) {}

            const finalDesc = desc || stateDesc;
            if (!finalDesc) return null;
            return {
                postDescription: finalDesc,
                publishTime: publishTime || statePublishTime,
            };
        })()"""

        async def _run():
            version = _httpx.get("http://127.0.0.1:9222/json/version").json()
            browser_ws = version["webSocketDebuggerUrl"]

            # 找 target id
            async with _ws.connect(browser_ws, max_size=10_000_000) as bws:
                await bws.send(_json_mod.dumps({"id": 1, "method": "Target.getTargets"}))
                resp = _json_mod.loads(await bws.recv())
                targets = resp.get("result", {}).get("targetInfos", [])
                page_target = next(
                    (t for t in targets if t.get("type") == "page" and "zhipin.com" in t.get("url", "")),
                    None,
                )
                if not page_target:
                    return None
                tid = page_target["targetId"]

            target_ws = f"ws://127.0.0.1:9222/devtools/page/{tid}"
            async with _ws.connect(target_ws, max_size=10_000_000) as tws:
                # 先启用 Page 域才能收到导航事件
                await tws.send(_json_mod.dumps({"id": 19, "method": "Page.enable"}))
                # 消耗 Page.enable 的回复
                for _ in range(5):
                    raw = await asyncio.wait_for(tws.recv(), timeout=2.0)
                    if _json_mod.loads(raw).get("id") == 19:
                        break

                # 导航到详情页
                await tws.send(_json_mod.dumps({
                    "id": 20, "method": "Page.navigate",
                    "params": {"url": detail_url},
                }))

                # 等待 domContentEventFired 或 loadEventFired
                for _ in range(60):
                    try:
                        raw = await asyncio.wait_for(tws.recv(), timeout=2.0)
                    except asyncio.TimeoutError:
                        break
                    msg = _json_mod.loads(raw)
                    method = msg.get("method", "")
                    if method in ("Page.domContentEventFired", "Page.loadEventFired"):
                        break
                    if msg.get("id") == 20 and "error" in msg:
                        return None

                await asyncio.sleep(0.8)

                # 提取内容
                await tws.send(_json_mod.dumps({
                    "id": 21, "method": "Runtime.evaluate",
                    "params": {"expression": JS_EXTRACT, "returnByValue": True},
                }))
                for _ in range(30):
                    try:
                        raw = await asyncio.wait_for(tws.recv(), timeout=3.0)
                    except asyncio.TimeoutError:
                        break
                    msg = _json_mod.loads(raw)
                    if msg.get("id") == 21:
                        val = msg.get("result", {}).get("result", {}).get("value")
                        return val  # dict or None

            return None

        try:
            return asyncio.run(_run())
        except Exception:
            return None

    def _collect_jobs_via_cdp(
        self,
        extra_keywords: list[str] | None = None,
        skip_ids: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """通过原生 CDP WebSocket 采集职位列表（替代 page.evaluate fetch）。"""
        keywords = [self.settings.keyword]
        if extra_keywords:
            keywords += [k for k in extra_keywords if k not in keywords]

        seen: dict[str, dict] = {}
        for kw in keywords:
            print(f"  关键词 {kw!r}:")
            for page_num in range(1, self.settings.max_pages + 1):
                params = {
                    "scene": "1", "query": kw, "city": self.settings.city,
                    "experience": "", "degree": "", "industry": "",
                    "scale": "", "stage": "", "position": "",
                    "salary": "", "multiBusinessDistrict": "",
                    "page": str(page_num), "pageSize": "20", "sortType": "1",
                }
                payload = self._cdp_fetch(_JOBLIST_URL, params)
                code = payload.get("code")
                if code == 37 or code == 36:
                    # 多次重试，逐步加长等待
                    for wait in [30, 60, 120]:
                        print(f"    第 {page_num} 页被限速 (code={code})，等待 {wait}s 后重试…")
                        time.sleep(wait)
                        payload = self._cdp_fetch(_JOBLIST_URL, params)
                        code = payload.get("code")
                        if code == 0:
                            break
                if code != 0:
                    print(f"    第 {page_num} 页异常 code={code} msg={payload.get('message')}")
                    break
                jobs = parse_joblist_payload(payload)
                if not jobs:
                    break
                new_count = 0
                for item in jobs:
                    jid = _job_id_from_item(item)
                    if jid and jid not in seen and (skip_ids is None or jid not in skip_ids):
                        seen[jid] = item
                        new_count += 1
                print(f"    第 {page_num} 页: {len(jobs)} 个, 新增 {new_count} (累计 {len(seen)})")
                time.sleep(random.uniform(4, 8))
            time.sleep(random.uniform(5, 10))
        return list(seen.values())

    def _make_httpx_headers(self, referer: str = "https://www.zhipin.com/") -> dict:
        return {
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
            "referer": referer,
            "user-agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
            ),
            "sec-ch-ua": '"Chromium";v="148", "Google Chrome";v="148", "Not-A.Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
            "sec-fetch-dest": "empty",
            "sec-fetch-site": "same-origin",
            "sec-fetch-mode": "cors",
            "priority": "u=1, i",
        }

    def _load_httpx_cookies(self) -> dict[str, str]:
        import json as _json
        data = _json.loads(self.settings.storage_state_path.read_text())
        return {c["name"]: c["value"] for c in data.get("cookies", [])}

    def scrape_httpx(
        self,
        *,
        max_jobs: int | None = None,
        extra_keywords: list[str] | None = None,
    ) -> Path:
        """全程 httpx 采集：列表 + card.json 详情，无需 Playwright 浏览器。"""
        import httpx as _httpx

        self._refresh_storage_state_from_chrome()
        cookies = self._load_httpx_cookies()
        headers = self._make_httpx_headers()
        exporter = JobExporter(self.settings.data_dir)
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)

        existing_ids: set[str] = set()
        if exporter.jsonl_path.exists():
            import json as _json
            for line in exporter.jsonl_path.read_text().splitlines():
                if line.strip():
                    try:
                        existing_ids.add(_json.loads(line).get("job_id", ""))
                    except Exception:
                        pass

        keywords = [self.settings.keyword]
        if extra_keywords:
            keywords += [k for k in extra_keywords if k not in keywords]

        seen: dict[str, dict] = {}
        with _httpx.Client(timeout=20, follow_redirects=False) as client:
            # ── 1. 列表采集 ──
            for kw in keywords:
                print(f"  关键词 {kw!r}:")
                for page_num in range(1, self.settings.max_pages + 1):
                    params = {
                        "scene": "1", "query": kw, "city": self.settings.city,
                        "experience": "", "degree": "", "industry": "",
                        "scale": "", "stage": "", "position": "",
                        "salary": "", "multiBusinessDistrict": "",
                        "page": str(page_num), "pageSize": "20", "sortType": "1",
                    }
                    resp = client.get(_JOBLIST_URL, params=params, headers=headers, cookies=cookies)
                    payload = resp.json()
                    code = payload.get("code")
                    if code != 0:
                        print(f"    第 {page_num} 页异常 code={code} msg={payload.get('message')}")
                        break
                    jobs = parse_joblist_payload(payload)
                    if not jobs:
                        break
                    new_count = 0
                    for item in jobs:
                        jid = _job_id_from_item(item)
                        if jid and jid not in seen and jid not in existing_ids:
                            seen[jid] = item
                            new_count += 1
                    print(f"    第 {page_num} 页: {len(jobs)} 个, 新增 {new_count} (累计 {len(seen)})")
                    time.sleep(random.uniform(3, 6))
                time.sleep(random.uniform(4, 8))

            items = list(seen.values())
            if max_jobs is not None:
                items = items[:max_jobs]
            print(f"列表共 {len(items)} 个职位，开始获取详情…")

            # ── 2. 详情采集（card.json） ──
            for idx, item in enumerate(items, start=1):
                job_id = _job_id_from_item(item)
                sid = item.get("securityId") or item.get("secId") or ""
                lid = item.get("lid") or ""
                print(f"[{idx}/{len(items)}] {job_id} …", end=" ", flush=True)

                card = {}
                if sid:
                    try:
                        r = client.get(
                            "https://www.zhipin.com/wapi/zpgeek/job/card.json",
                            params={"securityId": sid, "lid": lid},
                            headers=headers, cookies=cookies,
                        )
                        card = r.json().get("zpData", {}).get("jobCard", {}) or {}
                    except Exception as e:
                        print(f"card 请求失败: {e}", end=" ")

                record = normalize_job(item, card if card else None, job_id=job_id)
                if not record.get("job_description"):
                    self.failed_ids.append(job_id)
                    print("⚠ 无描述")
                else:
                    exporter.append(record)
                    print(f"✓ {record.get('job_title','')}")

                time.sleep(random.uniform(4, 8))

        failed_path = PROJECT_ROOT / "failed_ids.txt"
        if self.failed_ids:
            failed_path.write_text("\n".join(self.failed_ids) + "\n", encoding="utf-8")
        total = exporter.count if hasattr(exporter, "count") else "?"
        print(f"\n完成: 输出 {exporter.jsonl_path}")
        return exporter.jsonl_path

    def _refresh_storage_state_from_chrome(self) -> bool:
        """用 browser_cookie3 从本机 Chrome 提取 Boss Cookie 写入 storage_state.json。"""
        try:
            import browser_cookie3, json as _json
            cj = browser_cookie3.chrome(domain_name=".zhipin.com")
            cookies = [
                {
                    "name": c.name, "value": c.value, "domain": c.domain,
                    "path": c.path, "expires": c.expires or -1,
                    "httpOnly": False, "secure": bool(c.secure), "sameSite": "None",
                }
                for c in cj
            ]
            if not cookies:
                return False
            state = {"cookies": cookies, "origins": []}
            self.settings.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
            self.settings.storage_state_path.write_text(
                _json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"已从本机 Chrome 同步 {len(cookies)} 个 Boss Cookie → storage_state.json")
            return True
        except Exception as e:
            print(f"Cookie 同步失败: {e}")
            return False

    def scrape(
        self,
        *,
        require_login: bool = True,
        max_jobs: int | None = None,
        extra_keywords: list[str] | None = None,
    ) -> Path:
        self.require_login = require_login
        if require_login:
            self._ensure_login()
        exporter = JobExporter(self.settings.data_dir)
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)

        # Load already-collected IDs so we skip them in list collection
        existing_ids: set[str] = set()
        if exporter.jsonl_path.exists():
            import json as _json
            for line in exporter.jsonl_path.read_text().splitlines():
                if line.strip():
                    try:
                        existing_ids.add(_json.loads(line).get("job_id", ""))
                    except Exception:
                        pass
        if existing_ids:
            print(f"已有 {len(existing_ids)} 条记录，将跳过重复 job_id")

        # 同步 Cookie 用于 card.json 详情请求
        self._refresh_storage_state_from_chrome()

        # ── 列表采集：原生 CDP WebSocket（绕过 Playwright connect_over_cdp）──
        if is_cdp_up(CDP_PORT):
            print("原生 CDP WebSocket 模式采集列表…")
            items = self._collect_jobs_via_cdp(
                extra_keywords=extra_keywords,
                skip_ids=existing_ids,
            )
        else:
            print("CDP 不可用，降级到 httpx 列表采集…")
            import httpx as _httpx
            cookies = self._load_httpx_cookies()
            headers = self._make_httpx_headers()
            keywords = [self.settings.keyword]
            if extra_keywords:
                keywords += [k for k in extra_keywords if k not in keywords]
            seen: dict[str, dict] = {}
            with _httpx.Client(timeout=20) as client:
                for kw in keywords:
                    for page_num in range(1, self.settings.max_pages + 1):
                        params = {"scene":"1","query":kw,"city":self.settings.city,
                                  "experience":"","degree":"","industry":"","scale":"",
                                  "stage":"","position":"","salary":"","multiBusinessDistrict":"",
                                  "page":str(page_num),"pageSize":"20","sortType":"1"}
                        resp = client.get(_JOBLIST_URL, params=params, headers=headers, cookies=cookies)
                        payload = resp.json()
                        if payload.get("code") != 0:
                            break
                        for item in parse_joblist_payload(payload):
                            jid = _job_id_from_item(item)
                            if jid and jid not in seen and jid not in existing_ids:
                                seen[jid] = item
                        time.sleep(random.uniform(3, 6))
            items = list(seen.values())

        if max_jobs is not None:
            items = items[:max_jobs]

        print(f"列表共发现 {len(items)} 个职位，开始获取详情（CDP 详情页）…")
        print(f"(每个职位间隔 8–15 秒，从真实 Chrome 提取描述和发布时间)")

        for idx, item in enumerate(items, start=1):
            job_id = _job_id_from_item(item)
            if not job_id:
                continue
            sid = item.get("securityId") or item.get("secId") or ""
            print(f"[{idx}/{len(items)}] {job_id} …", end=" ", flush=True)

            detail = self._cdp_fetch_detail(job_id, sid)
            record = normalize_job(item, detail, job_id=job_id)

            if not record.get("job_description"):
                self.failed_ids.append(job_id)
                print("⚠ 无描述")
            else:
                pt = record.get("publish_time") or ""
                exporter.append(record)
                print(f"✓ {record.get('job_title', '')} [{pt or '无发布时间'}]")

            time.sleep(random.uniform(8, 15))

        failed_path = PROJECT_ROOT / "failed_ids.txt"
        if self.failed_ids:
            failed_path.write_text("\n".join(self.failed_ids) + "\n", encoding="utf-8")
            print(f"失败 job_id 已写入 {failed_path}")

        print(
            f"\n完成: 新增 {exporter.written} 条, 跳过重复 {exporter.skipped} 条, "
            f"输出 {exporter.jsonl_path}"
        )
        return exporter.jsonl_path

    def scrape_failed(self, *, require_login: bool = True) -> Path:
        """Re-attempt job IDs from failed_ids.txt that still lack descriptions."""
        failed_path = PROJECT_ROOT / "failed_ids.txt"
        if not failed_path.exists():
            print("没有失败记录可重试。")
            from src.exporter import JobExporter as _JE
            return _JE(self.settings.data_dir).jsonl_path

        job_ids = [
            line.strip()
            for line in failed_path.read_text().splitlines()
            if line.strip()
        ]
        if not job_ids:
            print("failed_ids.txt 为空，无需重试。")
            from src.exporter import JobExporter as _JE
            return _JE(self.settings.data_dir).jsonl_path

        print(f"重试 {len(job_ids)} 个失败职位…")
        self.require_login = require_login
        if require_login:
            self._ensure_login()

        exporter = JobExporter(self.settings.data_dir)
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)

        use_cdp = is_cdp_up(CDP_PORT)
        use_storage_state = (
            not use_cdp and self.settings.storage_state_path.exists()
        )
        with sync_playwright() as p:
            if use_cdp:
                print("连接本机 Chrome（CDP 模式）…")
                browser, context = connect_cdp(p, CDP_PORT)
                boss_tabs = [pg for pg in context.pages if "zhipin.com" in (pg.url or "")]
                page = boss_tabs[0] if boss_tabs else context.new_page()
            elif use_storage_state:
                print("storage_state 模式…")
                browser, context = launch_with_storage_state(
                    p, self.settings.storage_state_path, headless=self.settings.headless,
                )
                page = context.new_page()
            else:
                browser = None
                context = launch_persistent(p, headless=self.settings.headless)
                page = context.new_page()

            self._ensure_stable_boss_page(page)
            print(f"(每个职位间隔 {_DETAIL_DELAY_LOW_S}–{_DETAIL_DELAY_HIGH_S} 秒)")

            still_failed: list[str] = []
            for idx, job_id in enumerate(job_ids, start=1):
                print(f"[{idx}/{len(job_ids)}] {job_id} …", end=" ", flush=True)
                item = {"encryptJobId": job_id}
                detail = self._fetch_detail_via_page(page, item)
                record = normalize_job(item, detail, job_id=job_id)

                if not record.get("job_description"):
                    still_failed.append(job_id)
                    print("⚠ 无描述")
                else:
                    exporter.append(record)
                    print(f"✓ {record.get('job_title', '')}")

                _human_delay()

            if browser is not None:
                browser.close()
            else:
                context.close()

        if still_failed:
            failed_path.write_text("\n".join(still_failed) + "\n", encoding="utf-8")
            print(f"{len(still_failed)} 个仍失败，已更新 {failed_path}")
        else:
            failed_path.unlink(missing_ok=True)
            print("所有失败职位重试成功！")

        print(
            f"\n完成: 新增 {exporter.written} 条, 跳过重复 {exporter.skipped} 条, "
            f"输出 {exporter.jsonl_path}"
        )
        return exporter.jsonl_path
