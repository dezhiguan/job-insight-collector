from __future__ import annotations

from datetime import datetime, timezone


def parse_repo(repo_data: dict, readme: str) -> dict:
    owner = repo_data.get("owner") or {}
    company = owner.get("login", "") if isinstance(owner, dict) else ""
    repo_name = str(repo_data.get("name") or "")
    repo_id = f"{company}/{repo_name}" if company and repo_name else ""

    description = repo_data.get("description")
    language = repo_data.get("language")
    topics = repo_data.get("topics")
    if not isinstance(topics, list):
        topics = []

    readme_text = readme or ""
    readme_preview = readme_text[:2000]

    pushed_at = repo_data.get("pushed_at") or ""
    repo_url = repo_data.get("html_url") or (
        f"https://github.com/{repo_id}" if repo_id else ""
    )

    return {
        "repo_id": repo_id,
        "company": company,
        "repo_name": repo_name,
        "description": description if description else "",
        "stars": int(repo_data.get("stargazers_count") or 0),
        "language": language if language else "",
        "topics": topics,
        "readme_preview": readme_preview,
        "pushed_at": pushed_at,
        "source": "github",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "repo_url": repo_url,
    }
