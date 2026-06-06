from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Any


class JobExporter:
    def __init__(self, data_dir: Path, *, filename: str | None = None) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if filename:
            self.jsonl_path = self.data_dir / filename
        else:
            today = date.today().strftime("%Y%m%d")
            self.jsonl_path = self.data_dir / f"jobs_{today}.jsonl"
        self._seen_ids = self._load_existing_ids()
        self.written = 0
        self.skipped = 0

    def _load_existing_ids(self) -> set[str]:
        seen: set[str] = set()
        if not self.jsonl_path.exists():
            return seen
        with self.jsonl_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                job_id = row.get("job_id")
                if job_id:
                    seen.add(str(job_id))
        return seen

    def append(self, record: dict[str, Any]) -> bool:
        job_id = str(record.get("job_id") or "")
        if not job_id:
            return False
        if job_id in self._seen_ids:
            self.skipped += 1
            return False
        with self.jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._seen_ids.add(job_id)
        self.written += 1
        return True

    def export_csv(self, output_path: Path | None = None) -> Path:
        out = output_path or self.jsonl_path.with_suffix(".csv")
        rows: list[dict[str, Any]] = []
        fieldnames: list[str] = []
        if not self.jsonl_path.exists():
            out.write_text("", encoding="utf-8")
            return out
        with self.jsonl_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                for key in row:
                    if key not in fieldnames:
                        fieldnames.append(key)
                rows.append(row)
        with out.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                flat = dict(row)
                if isinstance(flat.get("job_labels"), list):
                    flat["job_labels"] = ", ".join(flat["job_labels"])
                writer.writerow(flat)
        return out
