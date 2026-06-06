from __future__ import annotations

import re
from datetime import datetime, timezone

from playwright.sync_api import Page

SALARY_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?\s*[kK]|(?:\d+(?:\.\d+)?\s*万(?:/年)?))"
)
LEVEL_PATTERN = re.compile(
    r"\b([PT]\d+(?:[-/]\d+)?|\d+-\d+)\b",
    re.IGNORECASE,
)
CITY_PATTERN = re.compile(
    r"(北京|上海|广州|深圳|杭州|成都|南京|武汉|西安|苏州|"
    r"重庆|天津|长沙|合肥|厦门|青岛|大连|宁波|无锡|"
    r"郑州|济南|福州|昆明|哈尔滨|沈阳|长春|石家庄|南昌|"
    r"珠海|东莞|佛山|惠州|嘉兴|绍兴|温州|常州|南通|"
    r"贵阳|南宁|太原|兰州|乌鲁木齐|海口|三亚)"
)
YEAR_PATTERN = re.compile(r"(20\d{2})")


def _extract_post_id_from_url(url: str) -> str:
    match = re.search(r"/discuss/(\d+)", url)
    return match.group(1) if match else ""


def _first_visible_text(page: Page, selectors: list[str]) -> str:
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() == 0:
                continue
            text = loc.inner_text(timeout=2000).strip()
            if text:
                return text
        except Exception:
            continue
    return ""


def _extract_tags(page: Page) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    selectors = [
        ".tag-item",
        ".post-tag",
        ".nc-tag",
        ".discuss-tag",
        "[class*='tag-list'] a",
        "[class*='Tag']",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel)
            count = min(loc.count(), 30)
            for i in range(count):
                text = loc.nth(i).inner_text(timeout=1000).strip()
                if not text or text in seen:
                    continue
                if any(marker in text for marker in ("关注", "粉丝", "回复", "举报")):
                    continue
                seen.add(text)
                tags.append(text)
        except Exception:
            continue
    return tags


def _extract_meta_fields(page: Page) -> dict[str, str]:
    company = ""
    position = ""
    meta_text = _first_visible_text(
        page,
        [".post-info", ".discuss-info", ".nc-post-meta", "[class*='postMeta']"],
    )
    if meta_text:
        company_match = re.search(r"公司[:：]\s*([^\s|·]+)", meta_text)
        if company_match:
            company = company_match.group(1).strip()
        position_match = re.search(r"岗位[:：]\s*([^\s|·]+)", meta_text)
        if position_match:
            position = position_match.group(1).strip()

    for sel in ["[class*='company']", ".company-name"]:
        if company:
            break
        val = _first_visible_text(page, [sel])
        if val:
            company = val

    for sel in ["[class*='position']", ".job-name"]:
        if position:
            break
        val = _first_visible_text(page, [sel])
        if val:
            position = val

    return {"company": company, "position": position}


def _infer_from_title(title: str) -> dict[str, str]:
    company = ""
    position = ""
    if not title:
        return {"company": company, "position": position}

    company_match = re.search(
        r"([\u4e00-\u9fffA-Za-z0-9]+(?:科技|公司|集团|银行|研究院|实验室|工作室)?)",
        title,
    )
    if company_match:
        company = company_match.group(1).strip()

    position_match = re.search(
        r"([\u4e00-\u9fffA-Za-z0-9+/\-]+(?:开发|工程师|算法|产品|运营|测试|设计|实习|薪资))",
        title,
    )
    if position_match:
        position = position_match.group(1).strip()

    return {"company": company, "position": position}


def _first_regex_match(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def _extract_year(content: str, meta_text: str) -> str:
    for source in (meta_text, content):
        match = YEAR_PATTERN.search(source)
        if match:
            return match.group(1)
    return ""


def parse_salary_post(page: Page) -> dict:
    post_id = _extract_post_id_from_url(page.url)
    title = _first_visible_text(page, ["h1", ".post-title", ".discuss-title", ".nc-title"])
    if not title:
        try:
            title = page.title().strip()
        except Exception:
            title = ""

    content = _first_visible_text(
        page,
        [
            ".nc-post-content",
            ".discuss-main-content",
            ".post-topic-des",
            ".post-content",
            "[class*='postContent']",
        ],
    )
    meta_text = _first_visible_text(
        page,
        [".post-info", ".discuss-info", ".nc-post-meta", "[class*='postMeta']"],
    )

    meta = _extract_meta_fields(page)
    inferred = _infer_from_title(title)
    company = meta["company"] or inferred["company"]
    position = meta["position"] or inferred["position"]
    tags = _extract_tags(page)

    search_text = f"{title}\n{content}\n{' '.join(tags)}"
    base_monthly = _first_regex_match(SALARY_PATTERN, content)
    total_package = ""
    salary_matches = SALARY_PATTERN.findall(content)
    if len(salary_matches) > 1:
        total_package = salary_matches[1]
    elif salary_matches:
        total_package = salary_matches[0]
    if not base_monthly and salary_matches:
        base_monthly = salary_matches[0]

    level = _first_regex_match(LEVEL_PATTERN, search_text)
    city = _first_regex_match(CITY_PATTERN, search_text)
    year = _extract_year(content, meta_text)

    scraped_at = datetime.now(timezone.utc).isoformat()
    post_url = f"https://www.nowcoder.com/discuss/{post_id}" if post_id else page.url

    return {
        "post_id": post_id,
        "title": title,
        "company": company,
        "position": position,
        "level": level,
        "city": city,
        "year": year,
        "base_monthly": base_monthly,
        "total_package": total_package,
        "content": content,
        "tags": tags,
        "source": "niuke_salary",
        "scraped_at": scraped_at,
        "post_url": post_url,
    }
