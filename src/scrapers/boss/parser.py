from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _pick(data: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = data.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def _labels(data: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for key in ("jobLabels", "skills", "showSkills"):
        raw = data.get(key)
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str):
                    labels.append(item)
                elif isinstance(item, dict):
                    labels.append(_pick(item, "name", "label"))
    return [x for x in labels if x]


def build_jd_text(record: dict[str, Any]) -> str:
    parts = [
        f"岗位：{record.get('job_title', '')}",
        f"公司：{record.get('company_name', '')}",
    ]
    if record.get("salary_desc"):
        parts.append(f"薪资：{record['salary_desc']}")
    if record.get("city_name"):
        parts.append(f"城市：{record['city_name']}")
    if record.get("experience"):
        parts.append(f"经验：{record['experience']}")
    if record.get("education"):
        parts.append(f"学历：{record['education']}")
    if record.get("job_labels"):
        parts.append(f"标签：{', '.join(record['job_labels'])}")
    parts.append("招聘要求：")
    parts.append(record.get("job_description") or "")
    return "\n".join(parts).strip()


def normalize_job(
    list_item: dict[str, Any] | None,
    detail: dict[str, Any] | None,
    *,
    job_id: str | None = None,
) -> dict[str, Any]:
    """Merge list + detail API payloads into a unified record."""
    base: dict[str, Any] = {}
    if list_item:
        base.update(list_item)
    if detail:
        # detail often nests under jobInfo / zpData
        if "jobInfo" in detail and isinstance(detail["jobInfo"], dict):
            base.update(detail["jobInfo"])
        if "brandComInfo" in detail and isinstance(detail["brandComInfo"], dict):
            base.setdefault("brandComInfo", detail["brandComInfo"])
        base.update({k: v for k, v in detail.items() if k not in ("jobInfo",)})

    resolved_id = job_id or _pick(
        base, "encryptJobId", "jobId", "encryptId", "jid"
    )
    brand = base.get("brandComInfo") or {}
    if not isinstance(brand, dict):
        brand = {}

    record = {
        "job_id": resolved_id,
        "job_title": _pick(base, "jobName", "positionName", "title"),
        "salary_desc": _pick(base, "salaryDesc", "salary"),
        "city_name": _pick(base, "cityName", "city"),
        "experience": _pick(
            base, "jobExperience", "experienceName", "experience"
        ),
        "education": _pick(
            base, "jobDegree", "degreeName", "education"
        ),
        "company_name": _pick(
            base, "brandName", "companyName", default=_pick(brand, "brandName")
        ),
        "company_size": _pick(
            base, "brandScaleName", default=_pick(brand, "brandScaleName")
        ),
        "industry": _pick(
            base, "brandIndustryName", default=_pick(brand, "brandIndustryName")
        ),
        "job_labels": _labels(base),
        "job_description": _pick(
            base, "postDescription", "jobDesc", "description"
        ),
        "publish_time": _pick(
            base, "publishTime", "lastModifyTime", "updateTime"
        ),
        "security_id": _pick(base, "securityId", "secId"),
        "detail_url": (
            f"https://www.zhipin.com/job_detail/{resolved_id}.html"
            if resolved_id
            else ""
        ),
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }
    record["jd_text"] = build_jd_text(record)
    return record


def parse_joblist_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    zp = payload.get("zpData") or payload
    job_list = zp.get("jobList") or zp.get("list") or []
    if not isinstance(job_list, list):
        return []
    return [item for item in job_list if isinstance(item, dict)]


def parse_detail_payload(payload: dict[str, Any]) -> dict[str, Any]:
    zp = payload.get("zpData") or payload
    if isinstance(zp.get("jobInfo"), dict):
        return zp
    return zp if isinstance(zp, dict) else {}
