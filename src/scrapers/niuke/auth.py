from __future__ import annotations

import select
import sys
import time
from pathlib import Path
from typing import Any

import yaml
from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

from src.browser import (
    COMMON_ARGS,
    HEADED_ARGS,
    HEADLESS_ARGS,
    USER_AGENT,
    apply_stealth,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
NIUKE_USER_DATA_DIR = PROJECT_ROOT / "auth" / "niuke-profile"
NIUKE_HOME_URL = "https://www.nowcoder.com"
NIUKE_LOGIN_URL = "https://www.nowcoder.com/login"
LOGIN_CHECK_TIMEOUT_MS = 600_000


def load_niuke_config() -> dict[str, Any]:
    config_path = PROJECT_ROOT / "config.yaml"
    if not config_path.exists():
        return {}
    with config_path.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    niuke = cfg.get("niuke")
    return niuke if isinstance(niuke, dict) else {}


def is_logged_in(page: Page) -> bool:
    selectors = [".avatar", ".login-info", "[class*='userInfo']", "[class*='user-info']"]
    for sel in selectors:
        try:
            if page.locator(sel).first.is_visible(timeout=1000):
                return True
        except Exception:
            continue
    return False


def launch_niuke_persistent(
    playwright: Playwright,
    *,
    headless: bool = False,
) -> BrowserContext:
    NIUKE_USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    args = list(COMMON_ARGS) + (HEADLESS_ARGS if headless else HEADED_ARGS)
    context_kwargs: dict[str, Any] = {
        "user_data_dir": str(NIUKE_USER_DATA_DIR),
        "headless": headless,
        "args": args,
        "locale": "zh-CN",
        "timezone_id": "Asia/Shanghai",
        "user_agent": USER_AGENT,
        "viewport": None if not headless else {"width": 1280, "height": 900},
        "color_scheme": "light",
        "ignore_default_args": ["--enable-automation"],
        "extra_http_headers": {"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
    }

    last_error: Exception | None = None
    for channel in ("chrome", "msedge", None):
        try:
            kwargs = dict(context_kwargs)
            if channel:
                kwargs["channel"] = channel
            context = playwright.chromium.launch_persistent_context(**kwargs)
            apply_stealth(context)
            return context
        except Exception as e:
            last_error = e
            continue

    raise RuntimeError(
        "无法启动牛客浏览器，请安装 Google Chrome，或运行: "
        ".venv/bin/playwright install chromium\n"
        f"原始错误: {last_error}"
    )


def _wait_for_niuke_login(context: BrowserContext) -> Page | None:
    print()
    print("浏览器已打开牛客网登录页，请完成登录。")
    print("登录成功后回到此终端按 Enter；脚本每 2 秒自动检测，检测到会立即继续…")
    deadline = time.time() + LOGIN_CHECK_TIMEOUT_MS / 1000
    stdin_ok = sys.stdin is not None and sys.stdin.isatty()

    while time.time() < deadline:
        for page in context.pages:
            try:
                if is_logged_in(page):
                    print("\n已检测到牛客登录成功。")
                    return page
            except Exception:
                continue
        if stdin_ok:
            try:
                ready, _, _ = select.select([sys.stdin], [], [], 2.0)
                if ready:
                    sys.stdin.readline()
                    break
            except (OSError, ValueError):
                time.sleep(2)
        else:
            time.sleep(2)

    for page in context.pages:
        try:
            if is_logged_in(page):
                return page
        except Exception:
            continue
    return None


def interactive_niuke_login(*, headless: bool = False) -> None:
    with sync_playwright() as p:
        context = launch_niuke_persistent(p, headless=False)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(NIUKE_LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(1500)
        active = _wait_for_niuke_login(context)
        ok = active is not None and is_logged_in(active)
        context.close()
    if not ok:
        raise RuntimeError("未检测到牛客登录成功，请重试: python cli.py niuke-login")
    print(f"牛客登录成功，登录态已保存: {NIUKE_USER_DATA_DIR}")


def verify_niuke_login(*, headless: bool = True) -> bool:
    with sync_playwright() as p:
        context = launch_niuke_persistent(p, headless=headless)
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto(NIUKE_HOME_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(2000)
            ok = is_logged_in(page)
        except Exception:
            ok = False
        context.close()
    return ok
