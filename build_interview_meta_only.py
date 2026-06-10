"""Collect 100 GitHub interview repos via search API only (no README fetch).
Search API has separate limit (10/min); core API is rate-limited.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

SEARCH_QUERIES = [
    "java interview guide stars:>500 language:Java",
    "面试题 java stars:>200",
    "interview questions backend stars:>1000",
    "系统设计 面试 stars:>200",
    "leetcode interview guide stars:>500",
    "java 面经 stars:>100",
    "spring boot interview stars:>300",
    "distributed systems interview stars:>500",
    "mysql redis interview stars:>200",
    "java concurrent interview stars:>100",
    "java spring mysql redis interview answers stars:>50",
    "面试 算法 java stars:>100",
    "interview preparation java developer stars:>200",
    "technical interview cheatsheet stars:>300",
    "coding interview preparation stars:>500",
    "computer science interview stars:>500",
    "operating system interview stars:>300",
    "network protocol interview stars:>100",
]


def _headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h


def search_repos(query: str) -> list[dict]:
    url = "https://api.github.com/search/repositories"
    params = {"q": query, "sort": "stars", "order": "desc", "per_page": 30}
    try:
        r = httpx.get(url, params=params, headers=_headers(), timeout=20)
        remaining = r.headers.get("x-ratelimit-remaining", "?")
        reset = r.headers.get("x-ratelimit-reset", "?")
        print(f"  '{query[:55]}' → {r.status_code}, remaining={remaining}")
        if r.status_code == 200:
            return r.json().get("items", [])
        if r.status_code == 403:
            print(f"  Rate limited. Reset at: {reset}. Skipping remaining queries.")
            return []
    except Exception as e:
        print(f"  search error: {e}")
    return []


def _stars_str(stars: int) -> str:
    return f"{round(stars/1000,1)}k⭐" if stars >= 1000 else f"{stars}⭐"


def _freshness(date_str: str) -> str:
    from datetime import date
    if not date_str:
        return ""
    try:
        from datetime import datetime as dt
        d = dt.strptime(date_str[:10], "%Y-%m-%d").date()
        days = (date.today() - d).days
        if days <= 90:
            return "🟢 最新（3个月内）"
        elif days <= 365:
            return "🟡 较新（1年内）"
        elif days <= 730:
            return "🟠 参考（1-2年）"
        return "🔴 较旧（2年以上），仅供参考"
    except Exception:
        return ""


def build_doc(item: dict) -> dict:
    full_name = item["full_name"]
    owner, repo_name = full_name.split("/", 1)
    stars = item.get("stargazers_count", 0)
    description = item.get("description") or ""
    language = item.get("language") or ""
    topics = item.get("topics") or []
    pushed_at = (item.get("pushed_at") or "")[:10]
    stars_str = _stars_str(stars)
    fresh = _freshness(pushed_at)
    fresh_line = f"> 📅 最后更新：{pushed_at} · {fresh}" if pushed_at else ""

    lines = [
        f"# 【面试指南】{repo_name} · {stars_str}",
    ]
    if fresh_line:
        lines.append(fresh_line)
    lines += [
        "",
        f"**仓库**：{full_name}",
        f"**Star 数**：{stars_str}",
    ]
    if language:
        lines.append(f"**主要语言**：{language}")
    if description:
        lines.append(f"**简介**：{description}")
    if topics:
        lines += ["", "## 技术标签", ""]
        for t in topics[:12]:
            lines.append(f"- {t}")
    lines += [
        "",
        "---",
        f"来源：GitHub | {full_name} | 采集时间：{datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
    ]
    markdown = "\n".join(lines)

    return {
        "post_id": full_name.replace("/", "_"),
        "repo_id": full_name,
        "company": owner,
        "repo_name": repo_name,
        "stars": stars,
        "language": language,
        "description": description,
        "topics": topics,
        "pushed_at": pushed_at,
        "readme_preview": "",
        "filename": f"【面试指南】{repo_name} · {stars_str}.md",
        "content": markdown,
        "source": "github_interview_meta",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    seen: dict[str, dict] = {}

    for query in SEARCH_QUERIES:
        if len(seen) >= 200:
            break
        items = search_repos(query)
        for item in items:
            fqn = item["full_name"]
            if fqn not in seen:
                seen[fqn] = item
        print(f"  cumulative unique repos: {len(seen)}")
        time.sleep(7)  # search rate limit: 10/min → ~8-9s interval is safe

    ranked = sorted(seen.values(), key=lambda x: x.get("stargazers_count", 0), reverse=True)[:100]
    print(f"\nTop {len(ranked)} repos selected (metadata only, no README fetching)")

    out_path = Path("data/github_interview_repos.jsonl")
    records = [build_doc(item) for item in ranked]

    with out_path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"写入 {len(records)} 条 → {out_path}")
    if records:
        print("\n=== 样本 ===")
        print(records[0]["content"][:400])


if __name__ == "__main__":
    main()
