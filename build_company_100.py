"""Build 100 company profile documents from Boss JD data."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

TARGET_CITIES = {
    "广州", "深圳", "上海", "北京", "杭州",
    "成都", "武汉", "西安", "南京", "苏州",
}

WELFARE_PATTERNS = [
    "双休", "大小周", "弹性工作", "弹性时间",
    "五险一金", "六险一金", "补充医疗",
    "接受居家办公", "远程办公",
    "年终奖", "股票期权", "股权激励",
    "带薪年假", "餐补", "交通补贴", "住房补贴",
    "不加班", "996", "965",
    "13薪", "14薪", "15薪", "16薪", "18薪", "20薪",
]
WFH_POSITIVE = {"居家办公", "接受居家办公", "远程办公"}
WFH_NEGATIVE = {"不接受居家办公"}


def parse_salary(desc: str):
    if not desc:
        return None
    d = desc.strip().upper()
    m = re.search(r"(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\s*K", d)
    if m:
        return round(float(m.group(1))), round(float(m.group(2)))
    m = re.search(r"(\d+(?:\.\d+)?)\s*K", d)
    if m:
        v = round(float(m.group(1)))
        return v, v
    return None


def extract_welfare(labels: list[str], desc: str) -> list[str]:
    found: set[str] = set()
    text = " ".join(labels) + " " + (desc or "")
    for pat in WELFARE_PATTERNS:
        if pat in text:
            found.add(pat)
    m = re.search(r"年假(\d+)天", text)
    if m:
        found.add(f"年假{m.group(1)}天")
    return sorted(found)


def freshness(date_str: str) -> str:
    if not date_str:
        return ""
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        days = (date.today() - dt).days
        if days <= 90:
            return "🟢 最新（3个月内）"
        elif days <= 365:
            return "🟡 较新（1年内）"
        return "🟠 参考（1-2年）"
    except Exception:
        return ""


def build_profile(company: str, jds: list[dict]) -> tuple[str, str]:
    cities = Counter(r.get("city_name", "") for r in jds)
    primary_city = cities.most_common(1)[0][0] if cities else ""

    # Tech stack
    all_labels: list[str] = []
    for r in jds:
        all_labels.extend(str(l).strip() for l in (r.get("job_labels") or []) if str(l).strip())
    label_counts = Counter(all_labels)
    welfare_set = set(WELFARE_PATTERNS) | WFH_POSITIVE | WFH_NEGATIVE
    tech_labels = [
        l for l, _ in label_counts.most_common(25)
        if l not in welfare_set and not re.match(r"^\d+薪$", l)
    ][:15]

    # Welfare
    welfare_counter: Counter = Counter()
    for r in jds:
        for w in extract_welfare(r.get("job_labels") or [], r.get("job_description") or ""):
            welfare_counter[w] += 1
    welfare_items = [w for w, _ in welfare_counter.most_common()]

    wfh_pos = sum(1 for r in jds if any(w in " ".join(r.get("job_labels") or []) for w in WFH_POSITIVE))
    wfh_neg = sum(1 for r in jds if any(w in " ".join(r.get("job_labels") or []) for w in WFH_NEGATIVE))
    if wfh_pos > wfh_neg:
        wfh_stance = f"支持居家办公（{wfh_pos}/{len(jds)} 岗位注明）"
    elif wfh_neg > wfh_pos:
        wfh_stance = f"要求到岗（{wfh_neg}/{len(jds)} 岗位注明不接受居家）"
    else:
        wfh_stance = "未明确"

    nth_bonuses = sorted(
        {re.search(r"(\d+)薪", r.get("salary_desc", "") or "").group(0)
         for r in jds if re.search(r"\d+薪", r.get("salary_desc", "") or "")},
        key=lambda x: int(x[:-1]), reverse=True,
    )

    # Salary range
    salary_pairs = [parse_salary(r.get("salary_desc", "")) for r in jds]
    valid_sal = [s for s in salary_pairs if s]
    if valid_sal:
        lows = [s[0] for s in valid_sal]
        highs = [s[1] for s in valid_sal]
        salary_summary = f"{min(lows)}-{max(highs)}K（均值 {round(sum(lows)/len(lows))}-{round(sum(highs)/len(highs))}K）"
    else:
        salary_summary = "未明确列出"

    # Dates
    dates = sorted(r.get("publish_time", "")[:10] for r in jds if r.get("publish_time"))
    latest_date = dates[-1] if dates else ""
    date_range = f"{dates[0]} ~ {dates[-1]}" if len(dates) >= 2 else (latest_date or "")

    # Company meta
    sizes = Counter(r.get("company_size", "") for r in jds if r.get("company_size"))
    industries = Counter(r.get("industry", "") for r in jds if r.get("industry"))
    company_size = sizes.most_common(1)[0][0] if sizes else ""
    industry = industries.most_common(1)[0][0] if industries else ""

    # Job titles
    title_cnt = Counter(r.get("job_title", "") for r in jds)
    top_titles = [t for t, _ in title_cnt.most_common(8) if t]

    # Exp distribution
    exp_cnt = Counter(r.get("experience", "不限") or "不限" for r in jds)

    city_list = "、".join(f"{c}（{n}）" for c, n in cities.most_common())
    fresh = freshness(latest_date)
    freshness_line = f"> 📅 数据更新：{date_range} · 来源：Boss直聘 · {fresh}" if date_range else ""

    h1_parts = [company, primary_city]
    if industry:
        h1_parts.append(industry)
    lines = ["# 【公司】" + " | ".join(h1_parts)]
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
    lines.append(f"**招聘城市**：{city_list}")

    lines += ["", "## 技术栈", ""]
    for l in tech_labels:
        lines.append(f"- {l}")

    lines += ["", "## 福利待遇", ""]
    lines.append(f"**办公方式**：{wfh_stance}")
    if nth_bonuses:
        lines.append(f"**薪资结构**：{'、'.join(nth_bonuses)}")
    welfare_display = [w for w in welfare_items
                       if w not in {"接受居家办公", "不接受居家办公", "居家办公", "远程办公"}
                       and not re.match(r"^\d+薪$", w)]
    if welfare_display:
        lines.append(f"**其他福利**：{'、'.join(welfare_display)}")

    lines += [
        "",
        "## 岗位动态",
        "",
        f"**当前在招岗位数**：{len(jds)} 个",
        f"**薪资范围**：{salary_summary}",
        f"**发布时间区间**：{date_range}",
        "",
        "**在招职位**：",
    ]
    for title in top_titles:
        cnt = title_cnt[title]
        lines.append(f"- {title}" + (f"（×{cnt}）" if cnt > 1 else ""))

    lines += ["", "**经验要求分布**："]
    for exp, cnt in sorted(exp_cnt.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"- {exp or '不限'}：{cnt} 个岗位")

    lines += ["", "---", f"数据来源：Boss直聘 | 采集时间：{latest_date or '2026-06-09'}"]
    markdown = "\n".join(lines)
    filename = f"【公司】{company} · {primary_city}.md"
    return filename, markdown


def score(item: tuple[str, list[dict]]) -> tuple[int, int]:
    jds = item[1]
    labels: set[str] = set()
    for r in jds:
        labels.update(str(l).strip() for l in (r.get("job_labels") or []))
    return (len(jds), len(labels))


def main() -> None:
    records: list[dict] = []
    with open("data/jobs_20260609.jsonl", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                pass

    company_jds: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        c = (r.get("company_name") or "").strip()
        if c:
            company_jds[c].append(r)

    def primary_city(jds: list[dict]) -> str:
        return Counter(r.get("city_name", "") for r in jds).most_common(1)[0][0] if jds else ""

    candidates = [
        (c, jds) for c, jds in company_jds.items()
        if primary_city(jds) in TARGET_CITIES
    ]
    top100 = sorted(candidates, key=score, reverse=True)[:100]

    out_path = Path("data/company_100.jsonl")
    now = datetime.now(timezone.utc).isoformat()
    count = 0

    with out_path.open("w", encoding="utf-8") as f:
        for company, jds in top100:
            filename, markdown = build_profile(company, jds)
            record = {
                "post_id": f"company_{company}",
                "company": company,
                "filename": filename,
                "content": markdown,
                "source": "boss_company_profile",
                "scraped_at": now,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1

    print(f"写入 {count} 条公司档案 → {out_path}")
    # preview
    with open("data/company_100.jsonl", encoding="utf-8") as f:
        first = json.loads(f.readline())
    print("\n=== 样本预览 ===")
    print(first["content"][:600])


if __name__ == "__main__":
    main()
