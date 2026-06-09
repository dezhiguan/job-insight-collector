from __future__ import annotations

from datetime import date, datetime


def _freshness_tier(date_str: str) -> str:
    if not date_str:
        return ""
    try:
        clean = str(date_str).strip()[:10]
        dt = datetime.strptime(clean, "%Y-%m-%d").date()
        days = (date.today() - dt).days
        if days <= 90:
            return "🟢 最新（3个月内）"
        elif days <= 365:
            return "🟡 较新（1年内）"
        elif days <= 730:
            return "🟠 参考（1-2年）"
        else:
            return "🔴 过期（2年以上），仅供参考"
    except Exception:
        return ""


def _meta_line(label: str, value: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        return ""
    return f"**{label}**：{text}"


def _join_list(items: list | None) -> str:
    if not items:
        return ""
    return ", ".join(str(item).strip() for item in items if str(item).strip())


def _sanitize(text: str, max_len: int = 20) -> str:
    safe = "".join(c for c in text if c not in r'\/:*?"<>|【】').strip()
    return safe[:max_len] if safe else ""


def _stars_str(stars) -> str:
    try:
        n = int(stars)
        return f"{round(n/1000, 1)}k⭐" if n >= 1000 else f"{n}⭐"
    except Exception:
        return ""


def build_boss_jd(record: dict) -> tuple[str, str] | tuple[None, None]:
    job_title = record.get("job_title") or ""
    company_name = record.get("company_name") or ""
    salary_desc = record.get("salary_desc") or ""
    city_name = record.get("city_name") or ""
    job_description = record.get("job_description") or ""

    if not job_title.strip() and len(job_description.strip()) < 50:
        return None, None

    c = _sanitize(city_name, 4)
    co = _sanitize(company_name, 15)
    jt = _sanitize(job_title, 20)
    sa = _sanitize(salary_desc, 12)
    parts = [p for p in [c, co, jt, sa] if p]
    filename = "【JD】" + " · ".join(parts) + ".md" if parts else "jd.md"

    scraped_at = str(record.get("scraped_at") or "")
    scraped_date = scraped_at[:10] if scraped_at else ""
    publish_time = record.get("publish_time") or ""
    freshness = _freshness_tier(publish_time)
    freshness_line = f"> 📅 {publish_time} · Boss直聘 · {freshness}" if publish_time else ""

    h1 = f"# 【JD】{company_name} | {job_title} | {salary_desc} | {city_name}"
    meta_lines = [
        _meta_line("公司", company_name),
        _meta_line("城市", city_name),
        _meta_line("薪资", salary_desc),
        _meta_line("发布时间", publish_time),
        _meta_line("经验", record.get("experience") or ""),
        _meta_line("学历", record.get("education") or ""),
        _meta_line("行业", record.get("industry") or ""),
        _meta_line("规模", record.get("company_size") or ""),
    ]
    labels = _join_list(record.get("job_labels"))
    if labels:
        meta_lines.append(_meta_line("技术标签", labels))

    body_lines = [line for line in meta_lines if line]
    footer = f"---\n采集时间：{scraped_date}" if scraped_date else "---"
    header = [h1, freshness_line, ""] if freshness_line else [h1, ""]
    markdown = "\n".join([*header, *body_lines, "", "## 职位描述", "", job_description, "", footer])
    return filename, markdown


def build_niuke_interview(record: dict) -> tuple[str, str]:
    post_id = str(record.get("post_id") or "")
    company = record.get("company") or ""
    position = record.get("position") or ""
    result = record.get("result") or ""
    content = record.get("content") or ""
    scraped_at = record.get("scraped_at") or ""
    interview_date = record.get("interview_date") or ""
    rounds = record.get("rounds") or 0

    co = _sanitize(company, 15)
    po = _sanitize(position, 15)
    re = _sanitize(result, 6)
    parts = [p for p in [co, po, re] if p]
    filename = "【面经】" + " · ".join(parts) + f" · {post_id[:6]}.md" if parts else f"niuke_interview_{post_id}.md"

    freshness = _freshness_tier(interview_date)
    freshness_line = f"> 📅 {interview_date} · 牛客面经 · {freshness}" if interview_date else ""

    h1 = f"# 【面经】{company} | {position} | {result}"
    meta_lines = [
        _meta_line("公司", company),
        _meta_line("岗位", position),
        _meta_line("面试结果", result),
    ]
    if rounds:
        meta_lines.append(f"**面试轮次**：{rounds} 轮")
    meta_lines.append(_meta_line("面试日期", interview_date))
    tags = _join_list(record.get("tags"))
    if tags:
        meta_lines.append(_meta_line("标签", tags))

    body_lines = [line for line in meta_lines if line]
    header = [h1, freshness_line, ""] if freshness_line else [h1, ""]
    markdown = "\n".join([
        *header, *body_lines, "",
        "## 面试详情", "", content, "",
        "---", f"来源：牛客面经 | 帖子ID：{post_id} | 采集时间：{scraped_at}",
    ])
    return filename, markdown


def build_niuke_salary(record: dict) -> tuple[str, str]:
    post_id = str(record.get("post_id") or "")
    company = record.get("company") or ""
    position = record.get("position") or ""
    level = record.get("level") or ""
    city = record.get("city") or ""
    content = record.get("content") or ""
    scraped_at = record.get("scraped_at") or ""
    year = record.get("year") or ""
    base_monthly = record.get("base_monthly") or ""
    total_package = record.get("total_package") or ""

    co = _sanitize(company, 12)
    po = _sanitize(position, 12)
    lv = _sanitize(level, 6)
    ci = _sanitize(city, 4)
    yr = _sanitize(year, 4)
    pos_level = f"{po}{lv}" if lv else po
    parts = [p for p in [co, pos_level, ci, (yr + "年") if yr else ""] if p]
    filename = "【薪资】" + " · ".join(parts) + f" · {post_id[:6]}.md" if parts else f"niuke_salary_{post_id}.md"

    freshness = _freshness_tier(f"{year}-01-01") if year else ""
    freshness_line = f"> 📅 {year}年 · 牛客薪资帖 · {freshness}" if year else ""

    h1 = f"# 【薪资】{company} | {position} {level} | {city} | {year}年"
    meta_lines = [
        _meta_line("公司", company),
        _meta_line("岗位", position),
        _meta_line("职级", level),
        _meta_line("城市", city),
        _meta_line("年份", year),
        _meta_line("月薪", base_monthly),
        _meta_line("总包", total_package),
    ]
    tags = _join_list(record.get("tags"))
    if tags:
        meta_lines.append(_meta_line("标签", tags))

    body_lines = [line for line in meta_lines if line]
    header = [h1, freshness_line, ""] if freshness_line else [h1, ""]
    markdown = "\n".join([
        *header, *body_lines, "",
        "## 详情", "", content, "",
        "---", f"来源：牛客薪资 | 帖子ID：{post_id} | 采集时间：{scraped_at}",
    ])
    return filename, markdown


def build_prebuilt(record: dict) -> tuple[str, str] | tuple[None, None]:
    """Pass-through builder for records that already have filename + content."""
    filename = record.get("filename") or ""
    content = record.get("content") or ""
    if not filename or len(content) < 100:
        return None, None
    return filename, content


def build_boss_salary_market(record: dict) -> tuple[str, str] | tuple[None, None]:
    return build_prebuilt(record)


def build_github_repo(record: dict, kb_type: str = "company") -> tuple[str, str]:
    company = str(record.get("company") or "")
    repo_name = str(record.get("repo_name") or "")
    stars = record.get("stars")
    stars_str = _stars_str(stars)
    language = record.get("language") or ""
    pushed_at = record.get("pushed_at") or ""
    freshness = _freshness_tier(pushed_at[:10]) if pushed_at else ""

    if kb_type == "interview":
        name_part = _sanitize(repo_name, 25)
        filename = f"【面试指南】{name_part} · {stars_str}.md" if stars_str else f"【面试指南】{name_part}.md"
        h1 = f"# 【面试指南】{repo_name}"
        section = "## 内容简介"
    else:
        co = _sanitize(company, 12)
        name_part = _sanitize(repo_name, 20)
        lang_part = f" · {language}" if language else ""
        filename = f"【{co}】{name_part}{lang_part} · {stars_str}.md" if stars_str else f"【{co}】{name_part}.md"
        h1 = f"# 【{company}】{repo_name}"
        section = "## 技术概览"

    frontmatter = ["---", "source: github"]
    repo_id = record.get("repo_id") or ""
    if company:
        frontmatter.append(f"company: {company}")
    if repo_id:
        frontmatter.append(f"repo: {repo_id}")
    if stars is not None:
        frontmatter.append(f"stars: {stars}")
    if language:
        frontmatter.append(f"language: {language}")
    topics = record.get("topics") or []
    topics_str = _join_list(topics)
    if topics_str:
        frontmatter.append(f"topics: {topics_str}")
    if pushed_at:
        frontmatter.append(f"pushed_at: {pushed_at}")
    if freshness:
        frontmatter.append(f"freshness: {freshness}")
    frontmatter.append("---")

    description = record.get("description") or ""
    readme_preview = record.get("readme_preview") or ""
    topic_items = [str(t).strip() for t in topics if str(t).strip()]

    body: list[str] = [h1, ""]
    if description:
        body.extend([description, ""])
    if topic_items:
        body.append("## 技术标签")
        for t in topic_items:
            body.append(f"- {t}")
        body.append("")
    if readme_preview:
        body.extend([section, "", readme_preview])

    markdown = "\n".join(frontmatter + [""] + body).strip() + "\n"
    return filename, markdown
