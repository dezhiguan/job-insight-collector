from __future__ import annotations

import time

import httpx

from src.scrapers.github.parser import parse_repo

GITHUB_API_BASE = "https://api.github.com"


class GitHubScraper:
    def __init__(self, token: str = "", delay_ms: int = 1000) -> None:
        self.delay_ms = delay_ms
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token.strip():
            headers["Authorization"] = f"Bearer {token.strip()}"
        self._headers = headers
        self._client = httpx.Client(
            base_url=GITHUB_API_BASE,
            headers=headers,
            timeout=30.0,
        )

    def close(self) -> None:
        self._client.close()

    def scrape_org(
        self,
        org: str,
        min_stars: int,
        max_repos: int,
        readme_max_chars: int,
    ) -> list[dict]:
        resp = self._client.get(
            f"/orgs/{org}/repos",
            params={
                "type": "public",
                "sort": "stars",
                "direction": "desc",
                "per_page": 100,
            },
        )
        resp.raise_for_status()
        repos = resp.json()
        if not isinstance(repos, list):
            return []

        filtered = [
            repo
            for repo in repos
            if isinstance(repo, dict)
            and not repo.get("fork")
            and int(repo.get("stargazers_count") or 0) >= min_stars
        ]
        selected = filtered[:max_repos]

        records: list[dict] = []
        for repo in selected:
            owner = repo.get("owner") or {}
            owner_name = owner.get("login", "") if isinstance(owner, dict) else ""
            repo_name = str(repo.get("name") or "")
            if not owner_name or not repo_name:
                continue

            time.sleep(self.delay_ms / 1000.0)
            readme = self._fetch_readme(owner_name, repo_name, readme_max_chars)
            records.append(parse_repo(repo, readme))
            time.sleep(self.delay_ms / 1000.0)

        return records

    def _fetch_readme(self, owner: str, repo_name: str, max_chars: int) -> str:
        try:
            resp = self._client.get(
                f"/repos/{owner}/{repo_name}/readme",
                headers={
                    **self._headers,
                    "Accept": "application/vnd.github.raw+json",
                },
            )
            if resp.status_code == 404:
                return ""
            resp.raise_for_status()
            return resp.text[:max_chars]
        except Exception:
            return ""
