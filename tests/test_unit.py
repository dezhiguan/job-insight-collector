"""Run with: python tests/test_unit.py"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.exporter import JobExporter  # noqa: E402
from src.scrapers.boss.parser import normalize_job, parse_joblist_payload  # noqa: E402


def test_parse_joblist() -> None:
    payload = {
        "zpData": {
            "jobList": [
                {"encryptJobId": "1", "jobName": "A"},
                {"encryptJobId": "2", "jobName": "B"},
            ]
        }
    }
    items = parse_joblist_payload(payload)
    assert len(items) == 2


def test_normalize_and_export() -> None:
    list_item = {
        "encryptJobId": "jid-1",
        "jobName": "Python开发",
        "salaryDesc": "15-25K",
        "brandName": "示例科技",
        "cityName": "上海",
    }
    detail = {"jobInfo": {"postDescription": "熟悉 Django\n熟悉爬虫"}}
    record = normalize_job(list_item, detail, job_id="jid-1")
    assert record["job_description"] == "熟悉 Django\n熟悉爬虫"
    assert "Python开发" in record["jd_text"]

    with tempfile.TemporaryDirectory() as tmp:
        exporter = JobExporter(Path(tmp), filename="out.jsonl")
        assert exporter.append(record) is True
        assert exporter.append(record) is False
        lines = (Path(tmp) / "out.jsonl").read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        loaded = json.loads(lines[0])
        assert loaded["job_id"] == "jid-1"


if __name__ == "__main__":
    test_parse_joblist()
    test_normalize_and_export()
    print("all unit tests passed")
