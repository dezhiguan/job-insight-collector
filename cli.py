from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from src.auth import interactive_login, verify_login
from src.config import load_settings
from src.exporter import JobExporter
from src.scrapers.boss.scraper import JobScraper
from src.scrapers.niuke.auth import (
    interactive_niuke_login,
    load_niuke_config,
    verify_niuke_login,
)
from src.scrapers.niuke.interview_scraper import NiukeInterviewScraper
from src.scrapers.niuke.salary_scraper import NiukeSalaryScraper


def cmd_login(args: argparse.Namespace) -> int:
    settings = load_settings(headless=False)
    interactive_login(settings.storage_state_path, headless=False)
    return 0


def cmd_chrome(args: argparse.Namespace) -> int:
    """Just launch your real Chrome with remote debugging (for manual login)."""
    from src.browser import CDP_PORT, is_cdp_up, launch_user_chrome

    if is_cdp_up(CDP_PORT):
        print(f"Chrome 已在调试端口 {CDP_PORT} 运行，无需重复启动。")
        return 0
    try:
        launch_user_chrome(CDP_PORT)
    except RuntimeError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    if is_cdp_up(CDP_PORT):
        print(f"已启动 Chrome（调试端口 {CDP_PORT}）。请在该窗口登录 Boss，然后运行 ./run.sh scrape")
        return 0
    print("Chrome 启动后未监听调试端口，请改用: ./run.sh login", file=sys.stderr)
    return 1


def cmd_scrape(args: argparse.Namespace) -> int:
    settings = load_settings(
        keyword=args.keyword,
        city=args.city,
        max_pages=args.max_pages,
        delay_ms=args.delay_ms,
        headless=args.headless,
    )
    scraper = JobScraper(settings)
    try:
        scraper.scrape(require_login=not args.no_login)
    except (FileNotFoundError, RuntimeError) as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    settings = load_settings()
    exporter = JobExporter(settings.data_dir, filename=args.input)
    if args.format == "csv":
        out = exporter.export_csv(
            Path(args.output) if args.output else None
        )
        print(f"CSV 已导出: {out}")
    else:
        print(f"JSONL 路径: {exporter.jsonl_path}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    from src.browser import USER_DATA_DIR

    settings = load_settings()
    if not USER_DATA_DIR.exists() and not settings.storage_state_path.exists():
        print("未找到登录态，请先运行: ./run.sh login")
        return 1
    ok = verify_login(headless=True)
    print("登录态有效" if ok else "登录态无效，请重新 login")
    return 0 if ok else 1


def cmd_niuke_login(args: argparse.Namespace) -> int:
    try:
        interactive_niuke_login(headless=False)
    except RuntimeError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    return 0


def _niuke_headless(args: argparse.Namespace) -> bool:
    if args.headless:
        return True
    return bool(load_niuke_config().get("headless", False))


def _write_niuke_records(
    settings,
    records: list[dict],
    *,
    filename_prefix: str,
) -> Path:
    filename = f"{filename_prefix}_{date.today().strftime('%Y%m%d')}.jsonl"
    exporter = JobExporter(settings.data_dir, filename=filename)
    for record in records:
        post_id = str(record.get("post_id") or "")
        if not post_id:
            continue
        exporter.append({**record, "job_id": post_id})
    print(
        f"完成: 写入 {exporter.written} 条, 跳过重复 {exporter.skipped} 条, "
        f"输出 {exporter.jsonl_path}"
    )
    return exporter.jsonl_path


def cmd_niuke_interview(args: argparse.Namespace) -> int:
    settings = load_settings()
    niuke_cfg = load_niuke_config()
    headless = _niuke_headless(args)
    if not verify_niuke_login(headless=headless):
        print("请先运行: python cli.py niuke-login", file=sys.stderr)
        return 1

    max_pages = (
        args.max_pages
        if args.max_pages is not None
        else int(niuke_cfg.get("max_pages", 5))
    )
    scraper = NiukeInterviewScraper(settings)
    try:
        records = scraper.scrape(
            company_id=args.company_id,
            max_pages=max_pages,
        )
    except RuntimeError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1

    _write_niuke_records(settings, records, filename_prefix="niuke_interview")
    return 0


def cmd_niuke_salary(args: argparse.Namespace) -> int:
    settings = load_settings()
    niuke_cfg = load_niuke_config()
    headless = _niuke_headless(args)
    if not verify_niuke_login(headless=headless):
        print("请先运行: python cli.py niuke-login", file=sys.stderr)
        return 1

    max_pages = (
        args.max_pages
        if args.max_pages is not None
        else int(niuke_cfg.get("max_pages", 5))
    )
    scraper = NiukeSalaryScraper(settings)
    try:
        records = scraper.scrape(max_pages=max_pages)
    except RuntimeError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1

    _write_niuke_records(settings, records, filename_prefix="niuke_salary")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="job-insight-collector",
        description="职位洞察数据采集器（浏览器自动化技术演示）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_login = sub.add_parser("login", help="打开你的 Chrome 登录并等待登录成功")
    p_login.set_defaults(func=cmd_login)

    p_chrome = sub.add_parser("chrome", help="仅启动带调试端口的本机 Chrome（手动登录用）")
    p_chrome.set_defaults(func=cmd_chrome)

    p_scrape = sub.add_parser("scrape", help="按关键词与城市抓取 JD")
    p_scrape.add_argument("--keyword", help="搜索关键词")
    p_scrape.add_argument("--city", help="城市 code，见 config.yaml")
    p_scrape.add_argument("--max-pages", type=int, help="最大列表页数")
    p_scrape.add_argument("--delay-ms", type=int, help="请求间隔毫秒")
    p_scrape.add_argument(
        "--headless",
        action="store_true",
        help="无头模式（默认有头，便于过验证码）",
    )
    p_scrape.add_argument(
        "--no-login",
        action="store_true",
        help="不登录直接爬公开列表（详情可能不完整）",
    )
    p_scrape.set_defaults(func=cmd_scrape)

    p_niuke_login = sub.add_parser("niuke-login", help="打开牛客网登录页并等待手动登录")
    p_niuke_login.set_defaults(func=cmd_niuke_login)

    p_niuke_interview = sub.add_parser("niuke-interview", help="抓取牛客面经帖子")
    p_niuke_interview.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="最大列表页数（默认读 config.yaml niuke.max_pages）",
    )
    p_niuke_interview.add_argument(
        "--company-id",
        help="按公司 ID 过滤面经",
    )
    p_niuke_interview.add_argument(
        "--headless",
        action="store_true",
        help="无头模式",
    )
    p_niuke_interview.set_defaults(func=cmd_niuke_interview)

    p_niuke_salary = sub.add_parser("niuke-salary", help="抓取牛客薪资帖子")
    p_niuke_salary.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="最大列表页数（默认读 config.yaml niuke.max_pages）",
    )
    p_niuke_salary.add_argument(
        "--headless",
        action="store_true",
        help="无头模式",
    )
    p_niuke_salary.set_defaults(func=cmd_niuke_salary)

    p_export = sub.add_parser("export", help="导出数据")
    p_export.add_argument(
        "--format",
        choices=("jsonl", "csv"),
        default="csv",
        help="导出格式",
    )
    p_export.add_argument("--input", help="指定 jsonl 文件名（在 data/ 下）")
    p_export.add_argument("--output", help="csv 输出路径")
    p_export.set_defaults(func=cmd_export)

    p_check = sub.add_parser("check", help="检查登录态是否有效")
    p_check.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
