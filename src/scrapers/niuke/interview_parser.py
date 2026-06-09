from __future__ import annotations

import re
from datetime import datetime, timezone

from playwright.sync_api import Page

ROUND_KEYWORDS = ("一面", "二面", "三面", "终面", "hr面", "HR面")
RESULT_KEYWORDS = (
    ("offer", "offer"),
    ("oc", "offer"),
    ("已挂", "挂"),
    ("挂了", "挂"),
    ("待定", "待定"),
)


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
                if _looks_like_user_meta(text):
                    continue
                seen.add(text)
                tags.append(text)
        except Exception:
            continue
    return tags


def _looks_like_user_meta(text: str) -> bool:
    lowered = text.lower()
    skip_markers = ("关注", "粉丝", "回复", "举报", "收藏", "分享")
    return any(marker in text for marker in skip_markers)


def _extract_meta_fields(page: Page) -> dict[str, str]:
    company = ""
    position = ""
    interview_date = ""
    meta_selectors = [
        ".post-info",
        ".discuss-info",
        ".nc-post-meta",
        "[class*='postMeta']",
        "[class*='post-meta']",
    ]
    meta_text = _first_visible_text(page, meta_selectors)
    if meta_text:
        company_match = re.search(r"公司[:：]\s*([^\s|·]+)", meta_text)
        if company_match:
            company = company_match.group(1).strip()
        position_match = re.search(r"岗位[:：]\s*([^\s|·]+)", meta_text)
        if position_match:
            position = position_match.group(1).strip()
        date_match = re.search(r"(\d{4}[-/年]\d{1,2}[-/月]\d{1,2})", meta_text)
        if date_match:
            interview_date = date_match.group(1).replace("年", "-").replace("月", "-").replace("日", "")

    for sel in ["[class*='company']", ".company-name", "[class*='Company']"]:
        if company:
            break
        val = _first_visible_text(page, [sel])
        if val and "公司" not in val:
            company = val

    for sel in ["[class*='position']", ".job-name", "[class*='Position']"]:
        if position:
            break
        val = _first_visible_text(page, [sel])
        if val:
            position = val

    return {
        "company": company,
        "position": position,
        "interview_date": interview_date,
    }


def _infer_from_title(title: str) -> dict[str, str]:
    company = ""
    position = ""
    if not title:
        return {"company": company, "position": position}

    company_match = re.search(
        r"([\u4e00-\u9fffA-Za-z0-9]+(?:科技|公司|集团|银行|研究院|实验室|工作室)?)"
        r"(?:[\s·|-])?(?:[\u4e00-\u9fffA-Za-z0-9+/]+)?面经",
        title,
    )
    if company_match:
        company = company_match.group(1).strip()

    position_match = re.search(
        r"([\u4e00-\u9fffA-Za-z0-9+/\-]+(?:开发|工程师|算法|产品|运营|测试|设计|实习))"
        r".*面经",
        title,
    )
    if position_match:
        position = position_match.group(1).strip()

    return {"company": company, "position": position}


def _detect_result(content: str, tags: list[str]) -> str:
    haystack = f"{content} {' '.join(tags)}".lower()
    for keyword, label in RESULT_KEYWORDS:
        if keyword in haystack:
            return label
    return ""


def _count_rounds(content: str) -> int:
    total = 0
    for keyword in ROUND_KEYWORDS:
        total += len(re.findall(re.escape(keyword), content, flags=re.IGNORECASE))
    return total


def _parse_count(page: Page, selectors: list[str]) -> int:
    for sel in selectors:
        try:
            text = page.locator(sel).first.inner_text(timeout=1000).strip()
            match = re.search(r"(\d+)", text.replace(",", ""))
            if match:
                return int(match.group(1))
        except Exception:
            continue
    return 0


def parse_interview_post(page: Page) -> dict:
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
            ".nc-slate-editor-content",
            ".post-content-box",
            ".nc-post-content",
            ".discuss-main-content",
            ".post-topic-des",
            ".post-content",
            "[class*='postContent']",
        ],
    )

    meta = _extract_meta_fields(page)
    inferred = _infer_from_title(title)
    company = meta["company"] or inferred["company"]
    position = meta["position"] or inferred["position"]
    interview_date = meta["interview_date"]
    tags = _extract_tags(page)
    result = _detect_result(content, tags)
    rounds = _count_rounds(content)
    view_count = _parse_count(
        page,
        ["[class*='view']", ".view-count", "text=浏览"],
    )
    like_count = _parse_count(
        page,
        ["[class*='like']", ".like-count", "text=点赞", "text=赞"],
    )

    scraped_at = datetime.now(timezone.utc).isoformat()
    post_url = f"https://www.nowcoder.com/discuss/{post_id}" if post_id else page.url

    return {
        "post_id": post_id,
        "title": title,
        "company": company,
        "position": position,
        "result": result,
        "interview_date": interview_date,
        "rounds": rounds,
        "content": content,
        "tags": tags,
        "view_count": view_count,
        "like_count": like_count,
        "source": "niuke_interview",
        "scraped_at": scraped_at,
        "post_url": post_url,
    }
