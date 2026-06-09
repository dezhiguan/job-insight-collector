from __future__ import annotations

import socket
import subprocess
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, BrowserContext, Playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
USER_DATA_DIR = PROJECT_ROOT / "auth" / "chrome-profile"
CDP_PROFILE_DIR = PROJECT_ROOT / "auth" / "cdp-profile"
CDP_PORT = 9222

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = window.chrome || { runtime: {} };
Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
"""

COMMON_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-infobars",
    "--disk-cache-size=0",  # 禁用磁盘 cache，保证每次请求走网络，response listener 能捞到
]
HEADED_ARGS = ["--start-maximized"]
# Headless bundled Chromium can SIGSEGV with swiftshader; keep it minimal + GPU off.
HEADLESS_ARGS = ["--disable-gpu", "--window-size=1280,900"]

HOME_URL = "https://www.zhipin.com"
LOGIN_URL = "https://www.zhipin.com/web/user/?ka=header-login"
LOGIN_FALLBACK_URLS = [
    "https://www.zhipin.com/web/user/",
    "https://login.zhipin.com/?ka=header-login",
]


def apply_stealth(context: BrowserContext) -> None:
    try:
        context.add_init_script(STEALTH_INIT_SCRIPT)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# CDP attach mode: drive the user's REAL Chrome via remote debugging.
# This avoids automation-detection blank pages and crashpad spawn issues,
# because Chrome is started by the user's own shell/session, not Playwright.
# ---------------------------------------------------------------------------

def find_chrome() -> str | None:
    for path in CHROME_CANDIDATES:
        if Path(path).exists():
            return path
    return None


def is_cdp_up(port: int = CDP_PORT, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def launch_user_chrome(port: int = CDP_PORT) -> subprocess.Popen | None:
    """Start the user's real Chrome with remote debugging, detached.

    Returns the Popen handle (Chrome keeps running after this process exits).
    Returns None if Chrome is already listening on the port.
    """
    if is_cdp_up(port):
        return None
    chrome = find_chrome()
    if not chrome:
        raise RuntimeError(
            "未找到本机 Chrome，请安装 Google Chrome 后重试。"
        )
    CDP_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    args = [
        chrome,
        f"--remote-debugging-port={port}",
        f"--remote-allow-origins=http://127.0.0.1:{port}",
        f"--user-data-dir={CDP_PROFILE_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        "https://www.zhipin.com",
    ]
    proc = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    # wait for the debugging port to come up
    for _ in range(40):
        if is_cdp_up(port):
            break
        time.sleep(0.5)
    return proc


def connect_cdp(
    playwright: Playwright, port: int = CDP_PORT
) -> tuple[Browser, BrowserContext]:
    browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
    if browser.contexts:
        context = browser.contexts[0]
    else:
        context = browser.new_context()
    apply_stealth(context)
    return browser, context


def launch_persistent(
    playwright: Playwright,
    *,
    headless: bool = False,
) -> BrowserContext:
    """Launch a persistent (real-profile) context. Most resistant to bot checks.

    Cookies/login persist in USER_DATA_DIR across runs, so once you log in via
    `login`, both `check` and `scrape` reuse the same logged-in profile.
    """
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    args = list(COMMON_ARGS) + (HEADLESS_ARGS if headless else HEADED_ARGS)
    context_kwargs: dict[str, Any] = {
        "user_data_dir": str(USER_DATA_DIR),
        "headless": headless,
        "args": args,
        "locale": "zh-CN",
        "timezone_id": "Asia/Shanghai",
        "user_agent": USER_AGENT,
        # headed: let window size drive viewport; headless: fixed viewport
        "viewport": None if not headless else {"width": 1280, "height": 900},
        "color_scheme": "light",
        "ignore_default_args": ["--enable-automation"],
        "extra_http_headers": {"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
    }

    # Prefer real Chrome for both headed and headless (consistent profile format).
    # Bundled Chromium is the last-resort fallback.
    channels = ("chrome", "msedge", None)

    last_error: Exception | None = None
    for channel in channels:
        try:
            kwargs = dict(context_kwargs)
            if channel:
                kwargs["channel"] = channel
            context = playwright.chromium.launch_persistent_context(**kwargs)
            apply_stealth(context)
            return context
        except Exception as e:  # channel not installed / launch failed, try next
            last_error = e
            continue

    raise RuntimeError(
        "无法启动浏览器，请安装 Google Chrome，或运行: "
        ".venv/bin/playwright install chromium\n"
        f"原始错误: {last_error}"
    )


def launch_with_storage_state(
    playwright: Playwright,
    storage_state_path: Path,
    *,
    headless: bool = True,
) -> tuple[Browser, BrowserContext]:
    """Non-persistent context，从 storage_state.json 加载 cookies。
    headless=False 可在本地有头模式运行（绕过反爬），headless=True 用于云端。
    """
    args = list(COMMON_ARGS) + (HEADLESS_ARGS if headless else HEADED_ARGS)
    context_kwargs: dict[str, Any] = {
        "storage_state": str(storage_state_path),
        "locale": "zh-CN",
        "timezone_id": "Asia/Shanghai",
        "user_agent": USER_AGENT,
        "viewport": None if not headless else {"width": 1280, "height": 900},
        "color_scheme": "light",
        "extra_http_headers": {"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
    }
    launch_kwargs: dict[str, Any] = {
        "headless": headless,
        "args": args,
        "ignore_default_args": ["--enable-automation"],
    }

    last_error: Exception | None = None
    for channel in ("chrome", None):
        try:
            kwargs = dict(launch_kwargs)
            if channel:
                kwargs["channel"] = channel
            browser = playwright.chromium.launch(**kwargs)
            context = browser.new_context(**context_kwargs)
            apply_stealth(context)
            return browser, context
        except Exception as e:
            last_error = e
            continue

    raise RuntimeError(
        "无法启动云端浏览器，请运行: playwright install chromium\n"
        f"原始错误: {last_error}"
    )
