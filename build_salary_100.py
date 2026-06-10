"""Build 100 salary insight documents from Boss JD data.

Three document types:
  1. 城市×岗位 薪资行情报告 (city x category market)
  2. 公司薪资画像 (per-company salary profile)
  3. 全国岗位薪资综览 (national category overview)
"""
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


def categorize(title: str) -> str | None:
    t = title.lower()
    if "java" in t:
        return "Java开发"
    if "python" in t:
        return "Python开发"
    if "前端" in t or "react" in t or "vue" in t or "angular" in t:
        return "前端开发"
    if "算法" in t or " ai " in t or "大模型" in t or "nlp" in t or "机器学习" in t:
        return "AI/算法"
    if "大数据" in t or "flink" in t or "spark" in t or "hadoop" in t:
        return "大数据"
    if "运维" in t or "devops" in t or "sre" in t:
        return "运维/SRE"
    if "测试" in t:
        return "测试工程师"
    if "架构" in t:
        return "架构师"
    if "golang" in t or "go语言" in t or "go开发" in t:
        return "Go开发"
    if "c++" in t or "c/c++" in t:
        return "C++开发"
    if ("后端" in t or "服务端" in t) and "java" not in t and "python" not in t:
        return "后端开发"
    if "安卓" in t or "android" in t or "ios" in t:
        return "移动端开发"
    return None


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


def norm_exp(exp: str) -> str:
    if not exp:
        return "不限"
    if any(x in exp for x in ["应届", "在校", "实习", "0-1", "1年以下"]):
        return "0-1年（应届）"
    if any(x in exp for x in ["1-3", "2年", "3年"]):
        return "1-3年"
    if any(x in exp for x in ["3-5", "4年", "5年"]):
        return "3-5年"
    if any(x in exp for x in ["5-10", "6年", "7年", "8年", "10年", "10年以上"]):
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


def salary_stats(jds: list[dict]) -> dict:
    pairs = [parse_salary(r.get("salary_desc", "")) for r in jds]
    valid = [s for s in pairs if s]
    if not valid:
        return {"summary": "未明确列出薪资", "valid": 0, "pairs": []}
    lows = [s[0] for s in valid]
    highs = [s[1] for s in valid]
    return {
        "summary": (
            f"均值 {round(sum(lows)/len(lows))}-{round(sum(highs)/len(highs))}K"
            f"（区间 {min(lows)}-{max(highs)}K，样本 {len(valid)}/{len(jds)} 条）"
        ),
        "valid": len(valid),
        "pairs": list(zip(jds, pairs)),
    }


def exp_table(jds: list[dict]) -> list[str]:
    groups: dict[str, list] = defaultdict(list)
    for r in jds:
        sp = parse_salary(r.get("salary_desc", ""))
        if sp:
            groups[norm_exp(r.get("experience", ""))].append(sp)
    order = ["0-1年（应届）", "1-3年", "3-5年", "5年以上", "不限"]
    rows = []
    for exp in order:
        if exp in groups:
            rs = groups[exp]
            avg_l = round(sum(s[0] for s in rs) / len(rs))
            avg_h = round(sum(s[1] for s in rs) / len(rs))
            rows.append(f"| {exp} | {avg_l}-{avg_h}K | {len(rs)} 条 |")
    for exp in groups:
        if exp not in order:
            rs = groups[exp]
            avg_l = round(sum(s[0] for s in rs) / len(rs))
            avg_h = round(sum(s[1] for s in rs) / len(rs))
            rows.append(f"| {exp} | {avg_l}-{avg_h}K | {len(rs)} 条 |")
    return rows


def top_labels(jds: list[dict], n: int = 10) -> list[str]:
    all_l: list[str] = []
    for r in jds:
        all_l.extend(str(l).strip() for l in (r.get("job_labels") or []) if str(l).strip())
    welfare_set = {"不接受居家办公", "接受居家办公", "五险一金", "双休"}
    return [l for l, _ in Counter(all_l).most_common(20)
            if l not in welfare_set and not re.match(r"^\d+薪$", l)][:n]


# ── Document builders ─────────────────────────────────────────────────────────

def build_city_cat_doc(city: str, cat: str, jds: list[dict]) -> tuple[str, str]:
    dates = sorted(r.get("publish_time", "")[:10] for r in jds if r.get("publish_time"))
    date_range = f"{dates[0]} ~ {dates[-1]}" if len(dates) >= 2 else (dates[0] if dates else "")
    latest = dates[-1] if dates else ""
    fresh = freshness(latest)

    stats = salary_stats(jds)
    sizes = Counter(r.get("company_size", "") for r in jds if r.get("company_size"))
    title_cnt = Counter(r.get("job_title", "") for r in jds)

    lines = [
        f"# 【薪资行情】{city} · {cat}",
        f"> 📅 数据时间：{date_range} · 来源：Boss直聘 · {fresh}",
        "",
        f"**城市**：{city}",
        f"**岗位类别**：{cat}",
        f"**月薪（均值）**：{stats['summary']}",
        f"**样本量**：{len(jds)} 条在招JD",
        "",
        "## 经验等级薪资对照",
        "",
    ]
    lines.extend(exp_table(jds))
    labels = top_labels(jds)
    if labels:
        lines += ["", "## 高频技术要求", ""]
        lines.extend(f"- {l}" for l in labels)
    if sizes:
        lines += ["", "## 招聘公司规模", ""]
        lines.extend(f"- {sz}：{cnt} 家" for sz, cnt in sizes.most_common() if sz)
    top_titles = [t for t, _ in title_cnt.most_common(5) if t]
    if top_titles:
        lines += ["", "## 典型在招职位", ""]
        for t in top_titles:
            c = title_cnt[t]
            lines.append(f"- {t}" + (f"（×{c}）" if c > 1 else ""))
    lines += ["", "---", f"数据来源：Boss直聘 | 采集时间：{latest or '2026-06-09'}"]
    return f"【薪资行情】{city} · {cat}.md", "\n".join(lines)


def build_company_salary_doc(company: str, jds: list[dict]) -> tuple[str, str]:
    cities = Counter(r.get("city_name", "") for r in jds)
    primary = cities.most_common(1)[0][0] if cities else ""
    dates = sorted(r.get("publish_time", "")[:10] for r in jds if r.get("publish_time"))
    latest = dates[-1] if dates else ""
    fresh = freshness(latest)

    stats = salary_stats(jds)
    cats = Counter(categorize(r.get("job_title", "")) for r in jds)
    title_cnt = Counter(r.get("job_title", "") for r in jds)
    sizes = Counter(r.get("company_size", "") for r in jds if r.get("company_size"))
    company_size = sizes.most_common(1)[0][0] if sizes else ""

    lines = [
        f"# 【公司薪资】{company} · {primary}",
        f"> 📅 数据更新：{latest} · 来源：Boss直聘 · {fresh}",
        "",
        f"**公司名称**：{company}",
    ]
    if company_size:
        lines.append(f"**公司规模**：{company_size}")
    city_str = "、".join(f"{c}（{n}）" for c, n in cities.most_common())
    lines.append(f"**招聘城市**：{city_str}")
    lines += [
        "",
        "## 薪资概况",
        "",
        f"**当前在招岗位数**：{len(jds)} 个",
        f"**整体薪资区间**：{stats['summary']}",
        "",
        "## 经验等级薪资",
        "",
    ]
    lines.extend(exp_table(jds))
    lines += ["", "## 在招岗位及薪资", ""]
    for title, cnt in title_cnt.most_common(8):
        if not title:
            continue
        title_jds = [r for r in jds if r.get("job_title") == title]
        title_stats = salary_stats(title_jds)
        salary_str = title_stats["summary"].split("（")[0] if title_stats["valid"] else "未明确"
        cnt_str = f"（×{cnt}）" if cnt > 1 else ""
        lines.append(f"- **{title}**{cnt_str}：{salary_str}")
    lines += ["", "---", f"数据来源：Boss直聘 | 采集时间：{latest or '2026-06-09'}"]
    return f"【公司薪资】{company} · {primary}.md", "\n".join(lines)


def build_national_cat_doc(cat: str, jds: list[dict]) -> tuple[str, str]:
    cities = Counter(r.get("city_name", "") for r in jds)
    dates = sorted(r.get("publish_time", "")[:10] for r in jds if r.get("publish_time"))
    latest = dates[-1] if dates else ""
    fresh = freshness(latest)

    stats = salary_stats(jds)
    lines = [
        f"# 【薪资综览】{cat} · 全国行情",
        f"> 📅 数据时间：{dates[0] if dates else ''} ~ {latest} · 来源：Boss直聘 · {fresh}",
        "",
        f"**岗位类别**：{cat}",
        f"**覆盖城市**：{'、'.join(c for c,_ in cities.most_common())}",
        f"**月薪（均值）**：{stats['summary']}",
        f"**样本量**：{len(jds)} 条",
        "",
        "## 各城市薪资对比",
        "",
    ]
    for city, cnt in cities.most_common():
        city_jds = [r for r in jds if r.get("city_name") == city]
        city_stats = salary_stats(city_jds)
        lines.append(f"| {city} | {city_stats['summary'].split('（')[0]} | {cnt} 条 |")
    lines += ["", "## 全国经验等级薪资", ""]
    lines.extend(exp_table(jds))
    labels = top_labels(jds, 12)
    if labels:
        lines += ["", "## 高频技术要求（全国）", ""]
        lines.extend(f"- {l}" for l in labels)
    lines += ["", "---", f"数据来源：Boss直聘 | 采集时间：{latest or '2026-06-09'}"]
    return f"【薪资综览】{cat} · 全国.md", "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────

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

    # Group by city×cat
    city_cat_groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    cat_groups: dict[str, list[dict]] = defaultdict(list)
    company_groups: dict[str, list[dict]] = defaultdict(list)

    for r in records:
        cat = categorize(r.get("job_title", ""))
        city = r.get("city_name", "").strip()
        company = (r.get("company_name") or "").strip()
        if cat and city in TARGET_CITIES:
            city_cat_groups[(city, cat)].append(r)
            cat_groups[cat].append(r)
        if company and city in TARGET_CITIES:
            company_groups[company].append(r)

    out_path = Path("data/boss_salary_100.jsonl")
    now = datetime.now(timezone.utc).isoformat()
    output_records: list[dict] = []

    # Type 1: city x category (up to 50)
    for (city, cat), jds in sorted(city_cat_groups.items(), key=lambda x: len(x[1]), reverse=True)[:50]:
        filename, markdown = build_city_cat_doc(city, cat, jds)
        output_records.append({
            "post_id": f"salary_market_{city}_{cat}".replace(" ", "_"),
            "filename": filename,
            "content": markdown,
            "source": "boss_salary_market",
            "scraped_at": now,
        })

    # Type 2: per-company salary profiles (top companies by JD count)
    def score_co(item: tuple[str, list[dict]]) -> int:
        return len(item[1])

    company_sorted = sorted(company_groups.items(), key=score_co, reverse=True)
    for company, jds in company_sorted:
        if len(output_records) >= 96:
            break
        filename, markdown = build_company_salary_doc(company, jds)
        output_records.append({
            "post_id": f"company_salary_{company}",
            "filename": filename,
            "content": markdown,
            "source": "boss_company_salary",
            "scraped_at": now,
        })

    # Type 3: national category overviews (fill up to 100)
    for cat, jds in sorted(cat_groups.items(), key=lambda x: len(x[1]), reverse=True):
        if len(output_records) >= 100:
            break
        filename, markdown = build_national_cat_doc(cat, jds)
        output_records.append({
            "post_id": f"salary_national_{cat}".replace(" ", "_"),
            "filename": filename,
            "content": markdown,
            "source": "boss_national_salary",
            "scraped_at": now,
        })

    with out_path.open("w", encoding="utf-8") as f:
        for r in output_records[:100]:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    final = output_records[:100]
    by_type = Counter(r["source"] for r in final)
    print(f"写入 {len(final)} 条薪资文档 → {out_path}")
    print(f"类型分布: {dict(by_type)}")


if __name__ == "__main__":
    main()
