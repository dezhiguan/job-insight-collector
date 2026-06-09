"""Build salary market overview documents from Boss JD data and save as JSONL."""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple


class SalaryRange(NamedTuple):
    low: int
    high: int


def parse_salary(desc: str) -> SalaryRange | None:
    """Parse e.g. '15-25K' or '20K' into (low, high) in K."""
    if not desc:
        return None
    desc = desc.strip().upper()
    # e.g. '15-25K·14薪' or '15-25K'
    m = re.search(r"(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\s*K", desc)
    if m:
        return SalaryRange(round(float(m.group(1))), round(float(m.group(2))))
    m = re.search(r"(\d+(?:\.\d+)?)\s*K", desc)
    if m:
        v = round(float(m.group(1)))
        return SalaryRange(v, v)
    return None


def categorize(title: str) -> str:
    t = title.lower()
    if "java" in t:
        return "Java开发"
    if "python" in t:
        return "Python开发"
    if "前端" in t or "react" in t or "vue" in t:
        return "前端开发"
    if ("后端" in t or "服务端" in t) and "java" not in t and "python" not in t:
        return "后端开发（通用）"
    if "算法" in t or " ai " in t or "机器学习" in t or "大模型" in t or "nlp" in t:
        return "AI/算法"
    if "大数据" in t or "spark" in t or "hadoop" in t or "flink" in t:
        return "大数据"
    if "运维" in t or "devops" in t or "sre" in t:
        return "运维/SRE"
    if "测试" in t:
        return "测试工程师"
    if "架构" in t:
        return "架构师"
    return "全栈/其他开发"


def normalize_experience(exp: str) -> str:
    if not exp:
        return "不限"
    exp = exp.strip()
    if "1年" in exp or "0-1" in exp or "在校" in exp or "应届" in exp:
        return "0-1年（应届/初级）"
    if "1-3" in exp or "2年" in exp or "3年" in exp:
        return "1-3年（初中级）"
    if "3-5" in exp or "4年" in exp or "5年" in exp:
        return "3-5年（中级）"
    if "5-10" in exp or "6年" in exp or "7年" in exp or "8年" in exp or "10年" in exp:
        return "5年以上（高级）"
    return exp


def build_salary_document(category: str, city: str, items: list[dict]) -> str:
    salary_ranges = [parse_salary(r.get("salary_desc", "")) for r in items]
    valid = [s for s in salary_ranges if s]
    low_vals = [s.low for s in valid]
    high_vals = [s.high for s in valid]

    if valid:
        avg_low = round(sum(low_vals) / len(low_vals))
        avg_high = round(sum(high_vals) / len(high_vals))
        min_low = min(low_vals)
        max_high = max(high_vals)
        salary_summary = f"{avg_low}-{avg_high}K（区间：{min_low}K-{max_high}K，样本 {len(valid)} 条）"
    else:
        salary_summary = "暂无数据"

    # Group by experience
    exp_groups: dict[str, list[SalaryRange]] = defaultdict(list)
    for r, sr in zip(items, salary_ranges):
        if sr:
            exp_key = normalize_experience(r.get("experience", ""))
            exp_groups[exp_key].append(sr)

    # Collect labels/tech stack
    all_labels: list[str] = []
    for r in items:
        labels = r.get("job_labels") or []
        if isinstance(labels, list):
            all_labels.extend(str(l).strip() for l in labels if str(l).strip())
    from collections import Counter
    top_labels = [label for label, _ in Counter(all_labels).most_common(15)]

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    scraped_dates = sorted(
        r.get("scraped_at", "")[:10] for r in items if r.get("scraped_at")
    )
    latest_scraped = scraped_dates[-1] if scraped_dates else now

    lines = [
        f"# 【薪资行情】{city} · {category} · {now}",
        f"> 📅 数据采集：{latest_scraped} · 来源：Boss直聘 · 样本量：{len(items)} 条 JD",
        "",
        f"**城市**：{city}",
        f"**岗位类别**：{category}",
        f"**月薪区间（平均）**：{salary_summary}",
        "",
        "## 经验等级薪资分布",
        "",
    ]
    exp_order = ["0-1年（应届/初级）", "1-3年（初中级）", "3-5年（中级）", "5年以上（高级）"]
    shown_exp = set()
    for exp_key in exp_order:
        if exp_key in exp_groups:
            shown_exp.add(exp_key)
            rs = exp_groups[exp_key]
            avg_l = round(sum(s.low for s in rs) / len(rs))
            avg_h = round(sum(s.high for s in rs) / len(rs))
            lines.append(f"- **{exp_key}**：{avg_l}-{avg_h}K（{len(rs)} 条）")
    for exp_key in exp_groups:
        if exp_key not in shown_exp:
            rs = exp_groups[exp_key]
            avg_l = round(sum(s.low for s in rs) / len(rs))
            avg_h = round(sum(s.high for s in rs) / len(rs))
            lines.append(f"- **{exp_key}**：{avg_l}-{avg_h}K（{len(rs)} 条）")

    lines += ["", "## 高频技术要求", ""]
    for label in top_labels:
        lines.append(f"- {label}")

    lines += ["", "## 典型职位列表", ""]
    seen_titles: set[str] = set()
    for r in sorted(items, key=lambda x: parse_salary(x.get("salary_desc","")) or SalaryRange(0,0), reverse=True)[:10]:
        title = r.get("job_title", "")
        company = r.get("company_name", "")
        salary = r.get("salary_desc", "")
        exp = r.get("experience", "")
        key = f"{title}|{company}"
        if key not in seen_titles:
            seen_titles.add(key)
            lines.append(f"- {company} | **{title}** | {salary} | {exp}")

    lines += ["", "---", f"数据来源：Boss直聘 · 采集时间：{latest_scraped}"]
    return "\n".join(lines)


def main() -> None:
    records = []
    with open("data/jobs_20260609.jsonl", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                pass

    # Group by category + city
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in records:
        cat = categorize(r.get("job_title", ""))
        city = r.get("city_name", "").strip()
        if city and cat:
            groups[(cat, city)].append(r)

    # Pick top 3 groups by sample size (Java+北京, Java+广州, Python+北京, etc.)
    top_groups = sorted(groups.items(), key=lambda x: len(x[1]), reverse=True)

    out_path = Path("data/boss_salary_market.jsonl")
    count = 0
    with out_path.open("w", encoding="utf-8") as f:
        for (cat, city), items in top_groups[:10]:  # Top 10 groups
            if len(items) < 3:
                continue
            doc = build_salary_document(cat, city, items)
            filename = f"【薪资行情】{city} · {cat}.md"
            record = {
                "post_id": f"boss_salary_{city}_{cat}".replace(" ", "_"),
                "company": city,
                "position": cat,
                "city": city,
                "content": doc,
                "year": "2026",
                "source": "boss_jd_salary",
                "scraped_at": datetime.now(timezone.utc).isoformat(),
                "filename": filename,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
            print(f"  {filename}: {len(items)} JDs, content {len(doc)} chars")

    print(f"写入 {count} 条 -> {out_path}")


if __name__ == "__main__":
    main()
