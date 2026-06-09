"""Build rich company profile documents from Boss JD data."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

WELFARE_PATTERNS = [
    "双休", "大小周", "单休", "弹性工作", "弹性时间",
    "五险一金", "六险一金", "补充医疗",
    "居家办公", "接受居家办公", "不接受居家办公", "远程办公",
    "年终奖", "股票期权", "股权激励",
    "带薪年假", "餐补", "交通补贴", "住房补贴",
    "不加班", "996", "965", "995",
    "13薪", "14薪", "15薪", "16薪", "18薪", "20薪",
]

WFH_POSITIVE = {"居家办公", "接受居家办公", "远程办公"}
WFH_NEGATIVE = {"不接受居家办公"}


def extract_welfare(labels: list[str], desc: str) -> list[str]:
    found: set[str] = set()
    text = " ".join(labels) + " " + (desc or "")
    for pat in WELFARE_PATTERNS:
        if pat in text:
            found.add(pat)
    # Also pull year-leave patterns
    m = re.search(r"年假(\d+)天", text)
    if m:
        found.add(f"年假{m.group(1)}天")
    return sorted(found)


def extract_nth_salary(desc: str) -> str:
    """Extract nth-month bonus like 16薪."""
    m = re.search(r"(\d+)薪", desc or "")
    return f"{m.group(1)}薪" if m else ""


def parse_salary_k(desc: str) -> tuple[int, int] | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\s*K", desc.upper() if desc else "")
    if m:
        return round(float(m.group(1))), round(float(m.group(2)))
    m = re.search(r"(\d+(?:\.\d+)?)\s*K", desc.upper() if desc else "")
    if m:
        v = round(float(m.group(1)))
        return v, v
    return None


def build_company_profile(company: str, jds: list[dict]) -> tuple[str, str]:
    cities = Counter(r.get("city_name", "") for r in jds)
    primary_city = cities.most_common(1)[0][0] if cities else ""

    # ── Tech stack ──────────────────────────────────────────
    all_labels: list[str] = []
    for r in jds:
        labels = r.get("job_labels") or []
        all_labels.extend(str(l).strip() for l in labels if str(l).strip())
    label_counts = Counter(all_labels)
    # Exclude welfare-like labels from tech stack
    welfare_set = set(WELFARE_PATTERNS) | WFH_POSITIVE | WFH_NEGATIVE
    tech_labels = [
        l for l, _ in label_counts.most_common(20)
        if l not in welfare_set and not re.match(r"^\d+薪$", l)
    ][:15]

    # ── Welfare ──────────────────────────────────────────────
    welfare_found: Counter = Counter()
    for r in jds:
        labels = r.get("job_labels") or []
        desc = r.get("job_description") or ""
        for w in extract_welfare(labels, desc):
            welfare_found[w] += 1
    welfare_items = [w for w, _ in welfare_found.most_common()]

    # WFH stance
    wfh_pos = sum(1 for r in jds if any(
        w in " ".join(r.get("job_labels") or []) for w in WFH_POSITIVE
    ))
    wfh_neg = sum(1 for r in jds if any(
        w in " ".join(r.get("job_labels") or []) for w in WFH_NEGATIVE
    ))
    if wfh_pos > wfh_neg:
        wfh_stance = f"支持居家办公（{wfh_pos}/{len(jds)} 岗位注明接受）"
    elif wfh_neg > wfh_pos:
        wfh_stance = f"要求到岗（{wfh_neg}/{len(jds)} 岗位注明不接受居家）"
    else:
        wfh_stance = "未明确标注"

    # nth-month bonus from salary_desc
    nth_bonuses = [extract_nth_salary(r.get("salary_desc", "")) for r in jds]
    nth_bonuses = sorted({x for x in nth_bonuses if x}, key=lambda x: int(x[:-1]), reverse=True)

    # ── Job dynamics ─────────────────────────────────────────
    # Salary range across all positions
    salary_pairs = [parse_salary_k(r.get("salary_desc", "")) for r in jds]
    valid_salaries = [s for s in salary_pairs if s]
    if valid_salaries:
        lows = [s[0] for s in valid_salaries]
        highs = [s[1] for s in valid_salaries]
        salary_summary = f"{min(lows)}-{max(highs)}K（均值 {round(sum(lows)/len(lows))}-{round(sum(highs)/len(highs))}K，{len(valid_salaries)} 条）"
    else:
        salary_summary = "暂无"

    # Experience distribution
    exp_counter = Counter(r.get("experience", "不限") or "不限" for r in jds)

    # Job titles being recruited
    title_counter = Counter(r.get("job_title", "") for r in jds)
    top_titles = [t for t, _ in title_counter.most_common(8) if t]

    # Publish time range
    dates = sorted(
        r.get("publish_time", "")[:10]
        for r in jds if r.get("publish_time")
    )
    date_range = f"{dates[0]} ~ {dates[-1]}" if len(dates) >= 2 else (dates[0] if dates else "")

    # Cities hiring in
    city_list = [f"{c}（{n}）" for c, n in cities.most_common()]

    # Company size / industry
    sizes = Counter(r.get("company_size", "") for r in jds if r.get("company_size"))
    industries = Counter(r.get("industry", "") for r in jds if r.get("industry"))
    company_size = sizes.most_common(1)[0][0] if sizes else ""
    industry = industries.most_common(1)[0][0] if industries else ""

    # ── Build markdown ────────────────────────────────────────
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    freshness = _freshness_tier(dates[-1]) if dates else ""
    freshness_line = f"> 📅 数据更新：{dates[-1]} · 来源：Boss直聘 · {freshness}" if dates else ""

    h1_parts = [company, primary_city]
    if industry:
        h1_parts.append(industry)
    lines = [
        "# 【公司】" + " | ".join(h1_parts),
    ]
    if freshness_line:
        lines.append(freshness_line)
    lines += [
        "",
        f"**公司名称**：{company}",
    ]
    if company_size:
        lines.append(f"**公司规模**：{company_size}")
    if industry:
        lines.append(f"**所属行业**：{industry}")
    lines.append(f"**招聘城市**：{'、'.join(city_list)}")
    lines += [
        "",
        "## 技术栈",
        "",
    ]
    for label in tech_labels:
        lines.append(f"- {label}")

    lines += [
        "",
        "## 福利待遇",
        "",
    ]
    if wfh_stance:
        lines.append(f"**办公方式**：{wfh_stance}")
    if nth_bonuses:
        lines.append(f"**薪资结构**：{' / '.join(nth_bonuses)}")
    welfare_display = [w for w in welfare_items if w not in {
        "接受居家办公", "不接受居家办公", "居家办公", "远程办公"
    } and not re.match(r"^\d+薪$", w)]
    if welfare_display:
        lines.append(f"**其他福利**：{'、'.join(welfare_display)}")
    if not welfare_display and not nth_bonuses:
        lines.append("（JD 中未明确列出福利，请参考岗位描述）")

    lines += [
        "",
        "## 岗位动态",
        "",
        f"**当前在招岗位数**：{len(jds)} 个",
        f"**薪资范围**：{salary_summary}",
        f"**发布时间区间**：{date_range}",
        "",
        "**在招岗位列表**：",
    ]
    for title in top_titles:
        cnt = title_counter[title]
        suffix = f"（×{cnt}）" if cnt > 1 else ""
        lines.append(f"- {title}{suffix}")

    lines += [
        "",
        "**经验要求分布**：",
    ]
    for exp, cnt in sorted(exp_counter.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"- {exp or '不限'}：{cnt} 个")

    lines += [
        "",
        "---",
        f"数据来源：Boss直聘 | 采集时间：{now}",
    ]

    markdown = "\n".join(lines)
    filename = f"【公司】{company} · {primary_city}.md"
    return filename, markdown


def _freshness_tier(date_str: str) -> str:
    from datetime import date
    if not date_str:
        return ""
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
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

    # Group by company
    company_jds: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        company = (r.get("company_name") or "").strip()
        if company:
            company_jds[company].append(r)

    # Pick top 3 companies with most diverse tech labels
    def tech_diversity(jds: list[dict]) -> int:
        labels: set[str] = set()
        for r in jds:
            for l in (r.get("job_labels") or []):
                labels.add(str(l).strip())
        return len(labels)

    # Filter for target cities only
    TARGET_CITIES = {"广州", "深圳", "上海", "北京", "杭州"}

    def primary_city(jds: list[dict]) -> str:
        from collections import Counter
        cities = Counter(r.get("city_name", "") for r in jds)
        return cities.most_common(1)[0][0] if cities else ""

    candidates = [
        (company, jds)
        for company, jds in company_jds.items()
        if primary_city(jds) in TARGET_CITIES and len(jds) >= 2
    ]
    top3 = sorted(candidates, key=lambda x: tech_diversity(x[1]), reverse=True)[:3]

    out_path = Path("data/company_profiles.jsonl")
    with out_path.open("w", encoding="utf-8") as f:
        for company, jds in top3:
            filename, markdown = build_company_profile(company, jds)
            record = {
                "post_id": f"company_{company}",
                "company": company,
                "filename": filename,
                "content": markdown,
                "source": "boss_company_profile",
                "scraped_at": datetime.now(timezone.utc).isoformat(),
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(f"  {filename}: {len(jds)} JDs, {len(markdown)} chars")

    print(f"写入 {len(top3)} 条 -> {out_path}")
    print()

    # Preview first doc
    for company, jds in top3[:1]:
        _, md = build_company_profile(company, jds)
        print("=== PREVIEW ===")
        print(md)


if __name__ == "__main__":
    main()
