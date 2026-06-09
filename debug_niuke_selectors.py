"""One-shot debug: visit a known salary post and dump element info."""
from __future__ import annotations

from src.scrapers.niuke.auth import launch_niuke_persistent

POST_URL = "https://www.nowcoder.com/discuss/893428359751843840"  # 大疆嵌入式面经

CANDIDATE_CONTENT = [
    ".nc-post-content",
    ".discuss-main-content",
    ".post-topic-des",
    ".post-content",
    "[class*='postContent']",
    "[class*='content']",
    "article",
    "main",
    ".discuss-content",
    "[class*='discuss']",
    "[class*='post']",
    ".nc-content",
    "[class*='nc-']",
]

CANDIDATE_TITLE = [
    "h1",
    ".post-title",
    ".discuss-title",
    ".nc-title",
    "[class*='title']",
]

from playwright.sync_api import sync_playwright


def main() -> None:
    with sync_playwright() as p:
        ctx = launch_niuke_persistent(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(POST_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(3000)

        print("=== TITLE SELECTORS ===")
        for sel in CANDIDATE_TITLE:
            try:
                loc = page.locator(sel)
                c = loc.count()
                if c > 0:
                    text = loc.first.inner_text(timeout=2000).strip()
                    print(f"  {sel}  (count={c}): {repr(text[:120])}")
            except Exception as e:
                print(f"  {sel}  ERROR: {e}")

        print("\n=== CONTENT SELECTORS ===")
        for sel in CANDIDATE_CONTENT:
            try:
                loc = page.locator(sel)
                c = loc.count()
                if c > 0:
                    text = loc.first.inner_text(timeout=2000).strip()
                    print(f"  {sel}  (count={c}): {repr(text[:200])}")
            except Exception as e:
                print(f"  {sel}  ERROR: {e}")

        print("\n=== ALL CLASSES WITH 'post' or 'content' or 'discuss' ===")
        classes = page.evaluate("""
            () => {
                const all = document.querySelectorAll('*');
                const found = new Set();
                all.forEach(el => {
                    el.classList.forEach(cls => {
                        const l = cls.toLowerCase();
                        if (l.includes('post') || l.includes('content') || l.includes('discuss')) {
                            found.add(cls);
                        }
                    });
                });
                return Array.from(found).sort();
            }
        """)
        for cls in classes:
            print(f"  .{cls}")

        ctx.close()


if __name__ == "__main__":
    main()
