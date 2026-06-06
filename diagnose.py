"""Diagnostic: launch persistent Chrome, hit Boss pages, screenshot + report."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from playwright.sync_api import sync_playwright

from src.browser import HOME_URL, LOGIN_URL, launch_persistent

OUT = Path(__file__).resolve().parent / "data"
OUT.mkdir(parents=True, exist_ok=True)


def shot(page, name: str) -> None:
    p = OUT / name
    try:
        page.screenshot(path=str(p), full_page=False)
        print(f"  screenshot -> {p}")
    except Exception as e:
        print(f"  screenshot failed: {e}")


def probe(page, url: str, tag: str) -> None:
    print(f"[{tag}] goto {url}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(2500)
        print(f"  final url: {page.url}")
        print(f"  title    : {page.title()!r}")
        body_len = page.evaluate("() => document.body ? document.body.innerText.length : -1")
        html_len = page.evaluate("() => document.documentElement.outerHTML.length")
        print(f"  body text length: {body_len}, html length: {html_len}")
        login_btn = page.evaluate(
            "() => !!document.querySelector('a[ka=\"header-login\"], .login-btn, "
            ".btn-login, [class*=login]')"
        )
        print(f"  has login element: {login_btn}")
        shot(page, f"diag_{tag}.png")
    except Exception as e:
        print(f"  ERROR: {e}")


def main(headless: bool) -> None:
    print(f"launching persistent context (headless={headless}) …")
    with sync_playwright() as p:
        context = launch_persistent(p, headless=headless)
        bt = context.browser
        print(f"  browser version: {bt.version if bt else 'n/a (persistent)'}")
        page = context.pages[0] if context.pages else context.new_page()
        probe(page, HOME_URL, "home")
        probe(page, LOGIN_URL, "login")
        context.close()
    print("done.")


if __name__ == "__main__":
    headless = "--headless" in sys.argv
    main(headless)
