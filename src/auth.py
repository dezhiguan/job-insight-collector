from __future__ import annotations

import select
import sys
import time
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, sync_playwright

from src.browser import (
    CDP_PORT,
    HOME_URL,
    LOGIN_URL,
    connect_cdp,
    is_cdp_up,
    launch_persistent,
    launch_user_chrome,
)

LOGIN_CHECK_TIMEOUT_MS = 600_000  # 10 min for manual login


def _has_auth_cookie(context: BrowserContext) -> bool:
    try:
        cookies = context.cookies()
    except Exception:
        return False
    names = {c.get("name", "") for c in cookies}
    auth_markers = {"wt2", "zp_at", "__zp_stoken__", "bst"}
    return bool(names & auth_markers) or any(
        "zhipin" in (c.get("domain") or "") and c.get("name", "").startswith("wt")
        for c in cookies
    )


def is_logged_in(page: Page) -> bool:
    if _has_auth_cookie(page.context):
        return True
    selectors = [".nav-figure", "text=消息", ".nav-logout", "[class*='userinfo']"]
    for sel in selectors:
        try:
            if page.locator(sel).first.is_visible(timeout=1000):
                return True
        except Exception:
            continue
    return False


def _find_logged_in_page(context: BrowserContext) -> Page | None:
    for p2 in context.pages:
        try:
            if is_logged_in(p2):
                return p2
        except Exception:
            continue
    return None


def _ensure_boss_page(context: BrowserContext) -> Page:
    """Return an existing Boss tab, or open one."""
    for p2 in context.pages:
        try:
            if "zhipin.com" in (p2.url or ""):
                return p2
        except Exception:
            continue
    page = context.pages[0] if context.pages else context.new_page()
    for url in (HOME_URL, LOGIN_URL):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(1200)
            return page
        except Exception:
            continue
    return page


def _print_login_help() -> None:
    print()
    print("浏览器已打开 Boss 直聘（你本机的真实 Chrome）。请完成登录：")
    print("  - 点右上角「登录/注册」，微信扫码或手机号登录")
    print("  - 有滑块就手动拖动完成；关闭 VPN/代理更稳")
    print()


def _wait_for_login(context: BrowserContext) -> Page | None:
    """Poll on main thread only (Playwright sync API is NOT thread-safe)."""
    _print_login_help()
    print("登录成功后回到此终端按 Enter；脚本每 2 秒自动检测，检测到会立即继续…")
    deadline = time.time() + LOGIN_CHECK_TIMEOUT_MS / 1000
    stdin_ok = sys.stdin is not None and sys.stdin.isatty()

    while time.time() < deadline:
        logged = _find_logged_in_page(context)
        if logged:
            print("\n已检测到登录成功。")
            return logged
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
    return _find_logged_in_page(context)


def interactive_login(storage_state_path: Path, *, headless: bool = False) -> Path:
    """Primary: attach to the user's real Chrome over CDP (most reliable).

    Falls back to a Playwright persistent context if CDP attach is unavailable.
    """
    storage_state_path.parent.mkdir(parents=True, exist_ok=True)

    # 1) start (or reuse) the user's real Chrome with remote debugging
    try:
        launch_user_chrome(CDP_PORT)
    except RuntimeError as e:
        print(f"提示: {e}\n改用内置浏览器模式…")

    if is_cdp_up(CDP_PORT):
        print("正在连接你本机的 Chrome（CDP 模式）…")
        try:
            with sync_playwright() as p:
                browser, context = connect_cdp(p, CDP_PORT)
                _ensure_boss_page(context)
                active = _wait_for_login(context)
                ok = active is not None and is_logged_in(active)
                if ok:
                    try:
                        context.storage_state(path=str(storage_state_path))
                    except Exception:
                        pass
                browser.close()  # disconnect; the real Chrome keeps running
            if not ok:
                raise RuntimeError(
                    "未检测到登录成功。请在已打开的 Chrome 中登录后重试: ./run.sh login"
                )
            print("登录成功。该 Chrome 窗口请保持打开，然后运行: ./run.sh scrape ...")
            return storage_state_path
        except RuntimeError:
            raise
        except Exception as cdp_err:
            print(f"CDP 连接失败（{cdp_err}），改用持久化内置浏览器…")

    # 2) fallback: persistent context (works on machines without crashpad issue)
    print("未能连接本机 Chrome，改用持久化内置浏览器…")
    with sync_playwright() as p:
        context = launch_persistent(p, headless=False)
        _ensure_boss_page(context)
        active = _wait_for_login(context)
        ok = active is not None and is_logged_in(active)
        if ok:
            try:
                context.storage_state(path=str(storage_state_path))
            except Exception:
                pass
        context.close()
    if not ok:
        raise RuntimeError("未检测到登录成功，请重试: ./run.sh login")
    print(f"登录成功，登录态已保存: {storage_state_path}")
    return storage_state_path


def verify_login(*, headless: bool = True) -> bool:
    """Check login by attaching to the running Chrome (CDP), else persistent."""
    if is_cdp_up(CDP_PORT):
        with sync_playwright() as p:
            browser, context = connect_cdp(p, CDP_PORT)
            page = _ensure_boss_page(context)
            try:
                page.reload(wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(1500)
            except Exception:
                pass
            ok = is_logged_in(page)
            browser.close()
        return ok

    with sync_playwright() as p:
        context = launch_persistent(p, headless=headless)
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto(
                "https://www.zhipin.com/web/geek/job",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            page.wait_for_timeout(2000)
            ok = is_logged_in(page)
        except Exception:
            ok = False
        context.close()
    return ok


def verify_storage_state(storage_state_path: Path, *, headless: bool = True) -> bool:
    return verify_login(headless=headless)
