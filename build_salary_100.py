"""Build 100 salary market documents from Boss JD data (all city×category combos)."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import NamedTuple


class SalaryRange(NamedTuple):
    low: int
    high: int


def parse_salary(desc: str) -> SalaryRange | None:
    if not desc:
        return None
    d = desc.strip().upper()
    m = re.search(r"(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\s*K", d)
    if m:
        return SalaryRange(round(float(m.group(1))), round(float(m.group(2))))
    m = re.search(r"(\d+(?:\.\d+)?)\s*K", d)
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
    if "前端" in t or "react" in t or "vue" in t or "angular" in t:
        return "前端开发"
    if "算法" in t or " ai " in t or "大模型" in t or "nlp" in t or "机器学习" in t:
        return "AI/算法"
    if "大数据" in t or "flink" in t or "spark" in t or "hadoop" in t or "数据开发" in t:
        return "大数据开发"
    if "运维" in t or "devops" in t or "sre" in t:
        return "运维/SRE"
    if "测试" in t:
        return "测试工程师"
    if "架构" in t:
        return "架构师/技术专家"
    if "golang" in t or "go语言" in t or "go开发" in t:
        return "Go开发"
    if "c++" in t or "c/c++" in t:
        return "C++开发"
    if ("后端" in t or "服务端" in t) and "java" not in t and "python" not in t:
        return "后端开发（通用）"
    if "安卓" in t or "android" in t or "ios" in t or "移动端" in t:
        return "移动端开发"
    return "其他开发岗位"


def normalize_exp(exp: str) -> str:
    if not exp:
        return "不限"
    if any(x in exp for x in ["1年", "0-1", "应届", "在校", "实习"]):
        return "0-1年（应届）"
    if any(x in exp for x in ["1-3", "2年", "3年"]):
        return "1-3年"
    if any(x in exp for x in ["3-5", "4年", "5年"]):
        return "3-5年"
    if any(x in exp for x in ["5-10", "6年", "7年", "8年", "10年"]):
        return "5年以上"
    return exp.strip()


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


def build_doc(category: str, city: str, jds: list[dict]) -> tuple[str, str]:
    salary_pairs = [parse_salary(r.get("salary_desc", "")) for r in jds]
    valid = [s for s in salary_pairs if s]

    if valid:
        lows = [s.low for s in valid]
        highs = [s.high for s in valid]
        salary_summary = (
            f"均值 {round(sum(lows)/len(lows))}-{round(sum(highs)/len(highs))}K"
            f"（区间 {min(lows)}-{max(highs)}K，样本 {len(valid)} 条）"
        )
    else:
        salary_summary = f"暂无解析（样本 {len(jds)} 条，含薪资描述: {sum(1 for r in jds if r.get('salary_desc'))} 条）"

    # Experience breakdown
    exp_groups: dict[str, list[SalaryRange]] = defaultdict(list)
    for r, sr in zip(jds, salary_pairs):
        if sr:
            exp_groups[normalize_exp(r.get("experience", ""))].append(sr)

    # Tech labels
    all_labels: list[str] = []
    for r in jds:
        all_labels.extend(str(l).strip() for l in (r.get("job_labels") or []) if str(l).strip())
    welfare_set = {"不接受居家办公", "接受居家办公", "五险一金", "双休", "弹性工作",
                   "居家办公", "远程办公"}
    top_labels = [l for l, _ in Counter(all_labels).most_common(20)
                  if l not in welfare_set and not re.match(r"^\d+薪$", l)][:12]

    # Company size distribution
    sizes = Counter(r.get("company_size", "") for r in jds if r.get("company_size"))

    # Dates
    dates = sorted(r.get("publish_time", "")[:10] for r in jds if r.get("publish_time"))
    latest_date = dates[-1] if dates else ""
    date_range = f"{dates[0]} ~ {dates[-1]}" if len(dates) >= 2 else (dates[0] if dates else "")

    # Top titles
    title_cnt = Counter(r.get("job_title", "") for r in jds)
    top_titles = [t for t, _ in title_cnt.most_common(6) if t]

    fresh = freshness(latest_date)
    freshness_line = f"> 📅 数据时间：{date_range} · 来源：Boss直聘 · {fresh}" if date_range else ""

    lines = [f"# 【薪资行情】{city} · {category} · 2026"]
    if freshness_line:
        lines.append(freshness_line)
    lines += [
        "",
        f"**城市**：{city}",
        f"**岗位类别**：{category}",
        f"**月薪（均值区间）**：{salary_summary}",
        f"**样本量**：{len(jds)} 条在招JD",
        "",
        "## 经验等级薪资对照",
        "",
    ]
    exp_order = ["0-1年（应届）", "1-3年", "3-5年", "5年以上", "不限"]
    for exp_key in exp_order:
        if exp_key in exp_groups:
            rs = exp_groups[exp_key]
            avg_l = round(sum(s.low for s in rs) / len(rs))
            avg_h = round(sum(s.high for s in rs) / len(rs))
            lines.append(f"| {exp_key} | {avg_l}-{avg_h}K | {len(rs)} 条样本 |")
    for exp_key in exp_groups:
        if exp_key not in exp_order:
            rs = exp_groups[exp_key]
            avg_l = round(sum(s.low for s in rs) / len(rs))
            avg_h = round(sum(s.high for s in rs) / len(rs))
            lines.append(f"| {exp_key} | {avg_l}-{avg_h}K | {len(rs)} 条样本 |")

    if top_labels:
        lines += ["", "## 高频技术要求", ""]
        for l in top_labels:
            lines.append(f"- {l}")

    if sizes:
        lines += ["", "## 招聘公司规模分布", ""]
        for sz, cnt in sizes.most_common():
            if sz:
                lines.append(f"- {sz}：{cnt} 家")

    if top_titles:
        lines += ["", "## 在招典型职位", ""]
        for title in top_titles:
            cnt = title_cnt[title]
            lines.append(f"- {title}" + (f"（×{cnt}）" if cnt > 1 else ""))

    lines += [
        "",
        "---",
        f"数据来源：Boss直聘 | 采集时间：{latest_date or '2026-06-09'}",
    ]
    markdown = "\n".join(lines)
    filename = f"【薪资行情】{city} · {category}.md"
    return filename, markdown


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

    TARGET_CITIES = {
        "广州", "深圳", "上海", "北京", "杭州",
        "成都", "武汉", "西安", "南京", "苏州",
    }

    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in records:
        cat = categorize(r.get("job_title", ""))
        city = r.get("city_name", "").strip()
        if city in TARGET_CITIES:
            groups[(cat, city)].append(r)

    # All combos sorted by sample size
    all_combos = sorted(groups.items(), key=lambda x: len(x[1]), reverse=True)

    out_path = Path("data/boss_salary_100.jsonl")
    count = 0
    now = datetime.now(timezone.utc).isoformat()

    with out_path.open("w", encoding="utf-8") as f:
        for (cat, city), jds in all_combos:
            if count >= 100:
                break
            filename, markdown = build_doc(cat, city, jds)
            record = {
                "post_id": f"salary_{city}_{cat}".replace(" ", "_"),
                "company": city,
                "position": cat,
                "city": city,
                "year": "2026",
                "filename": filename,
                "content": markdown,
                "source": "boss_salary_market",
                "scraped_at": now,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1

    print(f"写入 {count} 条薪资行情报告 → {out_path}")

    # Print sample
    with open("data/boss_salary_100.jsonl", encoding="utf-8") as f:
        first = json.loads(f.readline())
    print("\n=== 样本预览 ===")
    print(first["content"][:600])


if __name__ == "__main__":
    main()
