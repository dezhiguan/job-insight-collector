from __future__ import annotations

import time

import httpx


class RagForgeClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self.api_key}

    def upload_text(
        self,
        kb_id: int,
        filename: str,
        content: str,
        overwrite: bool = False,
    ) -> dict:
        content_bytes = content.encode("utf-8")
        files = {"file": (filename, content_bytes, "text/markdown")}
        params = {"overwrite": str(overwrite).lower()}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.base_url}/api/v1/kb/{kb_id}/documents",
                headers=self._headers(),
                files=files,
                params=params,
            )
            resp.raise_for_status()
            return resp.json()

    def get_status(self, doc_id: int) -> str:
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(
                f"{self.base_url}/api/v1/documents/{doc_id}/status",
                headers=self._headers(),
            )
            resp.raise_for_status()
            body = resp.json()
            return body.get("data", {}).get("parseStatus", "unknown")

    def wait_for_completion(
        self, doc_id: int, *, poll_interval: int = 3, timeout_s: int = 120
    ) -> str:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            status = self.get_status(doc_id)
            if status in ("completed", "failed"):
                return status
            time.sleep(poll_interval)
        return "timeout"
