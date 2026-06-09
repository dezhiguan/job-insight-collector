"""Search GitHub for interview repos, fetch top-30 READMEs, build 100 documents."""
from __future__ import annotations

import base64
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

SEARCH_QUERIES = [
    "java interview guide language:java stars:>500",
    "面试题 java stars:>500",
    "backend interview guide stars:>500 language:Java",
    "interview questions programming stars:>1000",
    "系统设计 面试 stars:>500",
]

MAX_README_FETCHES = 30  # stay within 60/hr unauthenticated
README_DELAY = 3.0       # seconds between README calls


def _headers() -> dict[str, str]:
    h = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h


def search_repos(query: str, per_page: int = 100) -> list[dict]:
    url = "https://api.github.com/search/repositories"
    params = {"q": query, "sort": "stars", "order": "desc", "per_page": per_page}
    try:
        r = httpx.get(url, params=params, headers=_headers(), timeout=20)
        remaining = r.headers.get("x-ratelimit-remaining", "?")
        print(f"  search '{query[:50]}' → status={r.status_code} remaining={remaining}")
        if r.status_code == 200:
            return r.json().get("items", [])
        if r.status_code == 403:
            print("  Rate limited, sleeping 60s …")
            time.sleep(61)
            return []
    except Exception as e:
        print(f"  search error: {e}")
    return []


def fetch_readme(owner: str, repo: str) -> str:
    url = f"https://api.github.com/repos/{owner}/{repo}/readme"
    try:
        r = httpx.get(url, headers=_headers(), timeout=20)
        if r.status_code == 200:
            data = r.json()
            content = data.get("content", "")
            if content:
                raw = base64.b64decode(content).decode("utf-8", errors="replace")
                return raw[:4000]
        elif r.status_code == 403:
            print(f"  Rate limited on README {owner}/{repo}, sleeping 60s …")
            time.sleep(61)
    except Exception as e:
        print(f"  README error {owner}/{repo}: {e}")
    return ""


def build_interview_doc(item: dict, readme: str) -> dict:
    repo_id = item["full_name"]
    owner, repo_name = repo_id.split("/", 1)
    stars = item.get("stargazers_count", 0)
    description = item.get("description") or ""
    language = item.get("language") or ""
    topics = item.get("topics") or []
    pushed_at = (item.get("pushed_at") or "")[:10]

    stars_str = f"{round(stars/1000,1)}k⭐" if stars >= 1000 else f"{stars}⭐"

    return {
        "post_id": repo_id.replace("/", "_"),
        "repo_id": repo_id,
        "company": owner,
        "repo_name": repo_name,
        "stars": stars,
        "language": language,
        "description": description,
        "topics": topics,
        "pushed_at": pushed_at,
        "readme_preview": readme[:2000] if readme else "",
        "source": "github_interview",
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
        time.sleep(2)

    # Sort by stars, take top 100
    ranked = sorted(seen.values(), key=lambda x: x.get("stargazers_count", 0), reverse=True)[:100]
    print(f"\nTop 100 repos selected. Fetching READMEs for top {MAX_README_FETCHES} …")

    records: list[dict] = []
    for idx, item in enumerate(ranked):
        owner, repo_name = item["full_name"].split("/", 1)
        readme = ""
        if idx < MAX_README_FETCHES:
            print(f"  [{idx+1}/{MAX_README_FETCHES}] README {item['full_name']} ({item.get('stargazers_count',0)}⭐)")
            readme = fetch_readme(owner, repo_name)
            time.sleep(README_DELAY)
        record = build_interview_doc(item, readme)
        records.append(record)

    out_path = Path("data/github_interview_repos.jsonl")
    with out_path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    with_readme = sum(1 for r in records if r.get("readme_preview"))
    print(f"\n完成: {len(records)} 条 ({with_readme} 含README) → {out_path}")


if __name__ == "__main__":
    main()
