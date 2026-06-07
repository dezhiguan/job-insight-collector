from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    keyword: str
    city: str
    max_pages: int
    delay_ms: int
    data_dir: Path
    storage_state_path: Path
    headless: bool
    cities: dict[str, str]
    ragforge_url: str = ""
    ragforge_api_key: str = ""
    ragforge_enabled: bool = False
    http_proxy: str = ""
    github_token: str = ""

    @property
    def search_url(self) -> str:
        from urllib.parse import quote

        query = quote(self.keyword)
        return (
            f"https://www.zhipin.com/web/geek/job"
            f"?query={query}&city={self.city}"
        )


def _load_yaml_config() -> dict:
    config_path = PROJECT_ROOT / "config.yaml"
    if not config_path.exists():
        return {}
    with config_path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_settings(
    *,
    keyword: str | None = None,
    city: str | None = None,
    max_pages: int | None = None,
    delay_ms: int | None = None,
    headless: bool | None = None,
) -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    yaml_cfg = _load_yaml_config()
    defaults = yaml_cfg.get("defaults", {})
    cities = yaml_cfg.get("cities", {})

    def _int(name: str, fallback: int) -> int:
        raw = os.getenv(name)
        if raw is None:
            return fallback
        return int(raw)

    def _str(name: str, fallback: str) -> str:
        return os.getenv(name, fallback)

    resolved_keyword = keyword or _str("KEYWORD", defaults.get("keyword", "Java后端"))
    resolved_city = city or _str("CITY", str(defaults.get("city", "101010100")))
    if resolved_city and not resolved_city.isdigit():
        resolved_city = cities.get(resolved_city, resolved_city)
    resolved_max_pages = max_pages if max_pages is not None else _int(
        "MAX_PAGES", int(defaults.get("max_pages", 3))
    )
    resolved_delay_ms = delay_ms if delay_ms is not None else _int(
        "DELAY_MS", int(defaults.get("delay_ms", 2000))
    )
    resolved_headless = headless if headless is not None else _str(
        "HEADLESS", "false"
    ).lower() in ("1", "true", "yes")
    resolved_ragforge_url = _str("RAGFORGE_URL", "")
    resolved_ragforge_api_key = _str("RAGFORGE_API_KEY", "")
    resolved_ragforge_enabled = _str(
        "RAGFORGE_ENABLED", "false"
    ).lower() in ("1", "true", "yes")
    resolved_http_proxy = _str("HTTP_PROXY", "")
    resolved_github_token = _str("GITHUB_TOKEN", "")

    data_dir = PROJECT_ROOT / _str("DATA_DIR", "data")
    storage_state = PROJECT_ROOT / _str(
        "STORAGE_STATE_PATH", "auth/storage_state.json"
    )

    return Settings(
        keyword=resolved_keyword,
        city=resolved_city,
        max_pages=resolved_max_pages,
        delay_ms=resolved_delay_ms,
        data_dir=data_dir,
        storage_state_path=storage_state,
        headless=resolved_headless,
        cities=cities,
        ragforge_url=resolved_ragforge_url,
        ragforge_api_key=resolved_ragforge_api_key,
        ragforge_enabled=resolved_ragforge_enabled,
        http_proxy=resolved_http_proxy,
        github_token=resolved_github_token,
    )
