from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

import httpx
import yaml

from src.auth import interactive_login, verify_login
from src.config import load_settings
from src.exporter import JobExporter
from src.pipeline.chunk_builder import (
    build_boss_jd,
    build_github_repo,
    build_niuke_interview,
    build_niuke_salary,
)
from src.pipeline.ragforge_client import RagForgeClient
from src.scrapers.boss.scraper import JobScraper
from src.scrapers.github.repo_scraper import GitHubScraper
from src.scrapers.niuke.auth import (
    interactive_niuke_login,
    load_niuke_config,
    verify_niuke_login,
)
from src.scrapers.niuke.interview_scraper import NiukeInterviewScraper
from src.scrapers.niuke.salary_scraper import NiukeSalaryScraper

PROJECT_ROOT = Path(__file__).resolve().parent

PUSH_BUILDERS = {
    "boss": build_boss_jd,
    "niuke-interview": build_niuke_interview,
    "niuke-salary": build_niuke_salary,
    "github": build_github_repo,
}

PUSH_KB_CONFIG = {
    "boss": ("RAGFORGE_JD_KB_ID", "jd_kb_id"),
    "niuke-interview": ("RAGFORGE_INTERVIEW_KB_ID", "interview_kb_id"),
    "niuke-salary": ("RAGFORGE_SALARY_KB_ID", "salary_kb_id"),
    "github": ("RAGFORGE_GITHUB_KB_ID", "github_kb_id"),
}


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
        headless=args.headless or None,
    )
    scraper = JobScraper(settings)
    extra_kws = args.extra_keywords if args.extra_keywords else None
    try:
        scraper.scrape(
            require_login=not args.no_login,
            max_jobs=args.max_jobs,
            extra_keywords=extra_kws,
        )
    except (FileNotFoundError, RuntimeError) as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_retry(args: argparse.Namespace) -> int:
    settings = load_settings()
    scraper = JobScraper(settings)
    try:
        scraper.scrape_failed(require_login=True)
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


def _load_ragforge_yaml() -> dict:
    config_path = PROJECT_ROOT / "config.yaml"
    if not config_path.exists():
        return {}
    with config_path.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    ragforge = cfg.get("ragforge")
    return ragforge if isinstance(ragforge, dict) else {}


def _load_github_yaml() -> dict:
    config_path = PROJECT_ROOT / "config.yaml"
    if not config_path.exists():
        return {}
    with config_path.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    github = cfg.get("github")
    return github if isinstance(github, dict) else {}


def _resolve_kb_id(source: str) -> int:
    env_name, cfg_key = PUSH_KB_CONFIG[source]
    ragforge_cfg = _load_ragforge_yaml()
    raw = os.getenv(env_name)
    if raw is not None and str(raw).strip():
        return int(raw)
    return int(ragforge_cfg.get(cfg_key, 1))


def _iter_jsonl_records(path: Path):
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _extract_document_id(response: dict) -> int | None:
    for key in ("documentId", "document_id", "id"):
        value = response.get(key)
        if value is not None:
            return int(value)
    data = response.get("data")
    if isinstance(data, dict):
        for key in ("documentId", "document_id", "id"):
            value = data.get(key)
            if value is not None:
                return int(value)
    return None


def _response_exists(response: dict) -> bool:
    if response.get("exists") is True:
        return True
    data = response.get("data")
    if isinstance(data, dict) and data.get("exists") is True:
        return True
    return False


def cmd_push(args: argparse.Namespace) -> int:
    settings = load_settings()
    if not settings.ragforge_enabled or not settings.ragforge_url.strip():
        print("RAGForge 推送未启用，跳过上传")
        return 0

    jsonl_path = Path(args.file)
    if not jsonl_path.is_file():
        print(f"错误: 文件不存在: {jsonl_path}", file=sys.stderr)
        return 1

    builder = PUSH_BUILDERS[args.source]
    kb_id = _resolve_kb_id(args.source)
    client = RagForgeClient(
        settings.ragforge_url,
        settings.ragforge_api_key,
    )

    records = list(_iter_jsonl_records(jsonl_path))
    total = len(records)
    if total == 0:
        print("没有可推送的记录。", file=sys.stderr)
        return 1

    success = 0
    skipped = 0
    discarded = 0
    failed = 0

    for idx, record in enumerate(records, start=1):
        filename, markdown = builder(record)
        if filename is None:
            discarded += 1
            print(f"[{idx}/{total}] → 丢弃（数据不完整）")
            continue
        try:
            response = client.upload_text(kb_id, filename, markdown)
        except httpx.HTTPError as e:
            failed += 1
            print(f"[{idx}/{total}] {filename} → 失败: {e}", file=sys.stderr)
            continue

        if _response_exists(response):
            skipped += 1
            print(f"[{idx}/{total}] {filename} → 已存在，跳过")
            continue

        doc_id = _extract_document_id(response)
        status = response.get("parseStatus") or response.get("status") or "processing"
        if isinstance(response.get("data"), dict):
            status = response["data"].get("parseStatus", status)

        if doc_id is None:
            success += 1
            print(f"[{idx}/{total}] {filename} → 上传成功 ({status})")
            continue

        if args.wait:
            status = client.wait_for_completion(doc_id)

        success += 1
        print(f"[{idx}/{total}] {filename} → document_id={doc_id} ({status})")

    print(f"汇总: 成功 {success} 条，跳过（已存在）{skipped} 条，丢弃（数据不完整）{discarded} 条，失败 {failed} 条")
    return 0 if failed == 0 else 1


def cmd_github(args: argparse.Namespace) -> int:
    settings = load_settings()
    github_cfg = _load_github_yaml()

    max_repos = (
        args.max_repos
        if args.max_repos is not None
        else int(github_cfg.get("max_repos_per_org", 10))
    )
    min_stars = (
        args.min_stars
        if args.min_stars is not None
        else int(github_cfg.get("min_stars", 500))
    )
    output_dir = Path(args.output or "data/github/")
    delay_ms = int(github_cfg.get("delay_ms", 1000))
    readme_max_chars = int(github_cfg.get("readme_max_chars", 2000))

    output_dir.mkdir(parents=True, exist_ok=True)
    scraper = GitHubScraper(
        token=settings.github_token,
        delay_ms=delay_ms,
    )

    try:
        for org in args.orgs:
            print(f"抓取 GitHub org: {org} …")
            records = scraper.scrape_org(
                org,
                min_stars=min_stars,
                max_repos=max_repos,
                readme_max_chars=readme_max_chars,
            )
            out_path = output_dir / f"{org}_repos.jsonl"
            with out_path.open("w", encoding="utf-8") as f:
                for record in records:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(f"  写入 {len(records)} 条 -> {out_path}")
    except httpx.HTTPError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    finally:
        scraper.close()

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
    p_scrape.add_argument(
        "--max-jobs",
        type=int,
        default=None,
        help="最多抓取职位数（用于快速验证）",
    )
    p_scrape.add_argument(
        "--extra-keywords",
        nargs="+",
        default=None,
        help="额外搜索关键词（每个关键词补充最多15个新职位）",
    )
    p_scrape.set_defaults(func=cmd_scrape)

    p_retry = sub.add_parser("retry", help="重试 failed_ids.txt 中的失败职位")
    p_retry.set_defaults(func=cmd_retry)

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

    p_push = sub.add_parser("push", help="推送本地 JSONL 到 RAGForge")
    p_push.add_argument(
        "--source",
        required=True,
        choices=["boss", "niuke-interview", "niuke-salary", "github"],
        help="数据来源类型",
    )
    p_push.add_argument(
        "--file",
        required=True,
        help="JSONL 文件路径",
    )
    p_push.add_argument(
        "--wait",
        action="store_true",
        help="推送后等待每条记录处理完成",
    )
    p_push.set_defaults(func=cmd_push)

    p_github = sub.add_parser("github", help="抓取 GitHub org 公开仓库信息")
    p_github.add_argument(
        "--orgs",
        nargs="+",
        required=True,
        help="一个或多个 GitHub org 名",
    )
    p_github.add_argument(
        "--max-repos",
        type=int,
        default=None,
        help="每个 org 最多抓取仓库数（默认读 config.yaml github.max_repos_per_org）",
    )
    p_github.add_argument(
        "--min-stars",
        type=int,
        default=None,
        help="最低 star 数（默认读 config.yaml github.min_stars）",
    )
    p_github.add_argument(
        "--output",
        default="data/github/",
        help="输出目录，默认 data/github/",
    )
    p_github.set_defaults(func=cmd_github)

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
