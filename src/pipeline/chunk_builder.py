from __future__ import annotations


def _meta_line(label: str, value: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        return ""
    return f"**{label}**：{text}"


def _join_list(items: list | None) -> str:
    if not items:
        return ""
    return ", ".join(str(item).strip() for item in items if str(item).strip())


def _sanitize(text: str, max_len: int = 30) -> str:
    """去除文件名非法字符，截断过长部分。字段缺失返回空字符串。"""
    safe = "".join(c for c in text if c not in r'\/:*?"<>|').strip()
    return safe[:max_len] if safe else ""


def build_boss_jd(record: dict) -> tuple[str, str] | tuple[None, None]:
    job_title = record.get("job_title") or ""
    company_name = record.get("company_name") or ""
    salary_desc = record.get("salary_desc") or ""
    city_name = record.get("city_name") or ""
    job_description = record.get("job_description") or ""

    # 丢弃：职位和正文都为空，RAG 无价值
    if not job_title.strip() and len(job_description.strip()) < 50:
        return None, None

    # 标题只拼接非空字段，跳过空值和分隔符
    parts = [_sanitize(f) for f in [job_title, company_name, salary_desc, city_name] if f.strip()]
    filename = "-".join(p for p in parts if p) + ".md" or "jd.md"

    job_description = record.get("job_description") or ""
    scraped_at = str(record.get("scraped_at") or "")
    scraped_date = scraped_at[:10] if scraped_at else ""

    title = f"# {job_title} · {company_name} · {city_name}"
    meta_lines = [
        _meta_line("公司", company_name),
        _meta_line("城市", city_name),
        _meta_line("薪资", salary_desc),
        _meta_line("发布时间", record.get("publish_time") or ""),
        _meta_line("经验", record.get("experience") or ""),
        _meta_line("学历", record.get("education") or ""),
        _meta_line("行业", record.get("industry") or ""),
        _meta_line("规模", record.get("company_size") or ""),
    ]
    labels = _join_list(record.get("job_labels"))
    if labels:
        meta_lines.append(_meta_line("标签", labels))

    body_lines = [line for line in meta_lines if line]
    footer = f"---\n采集时间：{scraped_date}" if scraped_date else "---"
    markdown = "\n".join(
        [
            title,
            "",
            *body_lines,
            "",
            "## 职位描述",
            "",
            job_description,
            "",
            footer,
        ]
    )
    return filename, markdown


def build_niuke_interview(record: dict) -> tuple[str, str]:
    post_id = str(record.get("post_id") or "")
    filename = f"niuke_interview_{post_id}.md"

    company = record.get("company") or ""
    position = record.get("position") or ""
    result = record.get("result") or ""
    content = record.get("content") or ""
    scraped_at = record.get("scraped_at") or ""
    interview_date = record.get("interview_date") or ""
    rounds = record.get("rounds") or 0

    title = f"# 面经：{company} · {position} · {result}"
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
    markdown = "\n".join(
        [
            title,
            "",
            *body_lines,
            "",
            "## 面试详情",
            "",
            content,
            "",
            "---",
            f"来源：牛客面经 | 帖子ID：{post_id} | 采集时间：{scraped_at}",
        ]
    )
    return filename, markdown


def build_niuke_salary(record: dict) -> tuple[str, str]:
    post_id = str(record.get("post_id") or "")
    filename = f"niuke_salary_{post_id}.md"

    company = record.get("company") or ""
    position = record.get("position") or ""
    level = record.get("level") or ""
    city = record.get("city") or ""
    content = record.get("content") or ""
    scraped_at = record.get("scraped_at") or ""

    title = f"# Offer：{company} · {position} · {level} · {city}"
    meta_lines = [
        _meta_line("公司", company),
        _meta_line("岗位", position),
        _meta_line("职级", level),
        _meta_line("城市", city),
        _meta_line("年份", record.get("year") or ""),
        _meta_line("月薪", record.get("base_monthly") or ""),
        _meta_line("总包", record.get("total_package") or ""),
    ]
    tags = _join_list(record.get("tags"))
    if tags:
        meta_lines.append(_meta_line("标签", tags))

    body_lines = [line for line in meta_lines if line]
    markdown = "\n".join(
        [
            title,
            "",
            *body_lines,
            "",
            "## 详情",
            "",
            content,
            "",
            "---",
            f"来源：牛客薪资 | 帖子ID：{post_id} | 采集时间：{scraped_at}",
        ]
    )
    return filename, markdown


def build_github_repo(record: dict) -> tuple[str, str]:
    company = str(record.get("company") or "")
    repo_name = str(record.get("repo_name") or "")
    filename = f"github_{company}_{repo_name}.md"

    frontmatter = ["---", "source: github"]
    repo_id = record.get("repo_id") or ""
    if company:
        frontmatter.append(f"company: {company}")
    if repo_id:
        frontmatter.append(f"repo: {repo_id}")
    stars = record.get("stars")
    if stars is not None and stars != "":
        frontmatter.append(f"stars: {stars}")
    language = record.get("language") or ""
    if language:
        frontmatter.append(f"language: {language}")
    topics = record.get("topics") or []
    topics_str = _join_list(topics)
    if topics_str:
        frontmatter.append(f"topics: {topics_str}")
    pushed_at = record.get("pushed_at") or ""
    if pushed_at:
        frontmatter.append(f"pushed_at: {pushed_at}")
    frontmatter.append("---")

    body: list[str] = [f"# {repo_name}", ""]
    description = record.get("description") or ""
    if description:
        body.extend([description, ""])

    topic_items = [str(item).strip() for item in topics if str(item).strip()]
    if topic_items:
        body.append("## 技术标签")
        for topic in topic_items:
            body.append(f"- {topic}")
        body.append("")

    readme_preview = record.get("readme_preview") or ""
    if readme_preview:
        body.extend(["## README 摘要", "", readme_preview])

    markdown = "\n".join(frontmatter + [""] + body).strip() + "\n"
    return filename, markdown
