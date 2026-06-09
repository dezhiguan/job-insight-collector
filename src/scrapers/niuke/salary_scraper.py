from __future__ import annotations

from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

from src.config import Settings
from src.scrapers.niuke.auth import launch_niuke_persistent, load_niuke_config
from src.scrapers.niuke.interview_scraper import (
    _random_delay,
    check_login_required,
    collect_post_ids,
)
from src.scrapers.niuke.salary_parser import parse_salary_post


def build_salary_list_url(*, page_num: int = 1) -> str:
    params: dict[str, str] = {"type": "salary", "order": "newest"}
    if page_num > 1:
        params["page"] = str(page_num)
    return f"https://www.nowcoder.com/discuss?{urlencode(params)}"


class NiukeSalaryScraper:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        niuke_cfg = load_niuke_config()
        self.delay_ms = int(niuke_cfg.get("delay_ms", settings.delay_ms))
        self.headless = bool(niuke_cfg.get("headless", False))

    def scrape(self, max_pages: int = 5, max_records: int | None = None) -> list[dict]:
        records: list[dict] = []
        seen_post_ids: set[str] = set()

        with sync_playwright() as p:
            context = launch_niuke_persistent(p, headless=self.headless)
            list_page = context.pages[0] if context.pages else context.new_page()

            for page_num in range(1, max_pages + 1):
                if max_records and len(records) >= max_records:
                    break
                url = build_salary_list_url(page_num=page_num)
                list_page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                check_login_required(list_page)
                _random_delay(self.delay_ms)

                post_ids = collect_post_ids(list_page)
                for post_id in post_ids:
                    if max_records and len(records) >= max_records:
                        break
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
                        try:
                            detail_page.wait_for_selector(
                                ".nc-slate-editor-content",
                                timeout=10_000,
                            )
                        except Exception:
                            pass
                        record = parse_salary_post(detail_page)
                        if record.get("post_id"):
                            records.append(record)
                    finally:
                        detail_page.close()
                    _random_delay(self.delay_ms)

                if page_num < max_pages:
                    _random_delay(self.delay_ms)

            context.close()

        return records
