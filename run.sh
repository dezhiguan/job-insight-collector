#!/usr/bin/env bash
# 始终使用项目 .venv，避免系统 Python 缺依赖
set -e
cd "$(dirname "$0")"

if [[ ! -x .venv/bin/python ]]; then
  echo "未找到 .venv，请先执行："
  echo "  python3 -m venv .venv"
  echo "  .venv/bin/pip install -r requirements.txt"
  echo "  .venv/bin/playwright install chromium"
  exit 1
fi

exec .venv/bin/python cli.py "$@"
