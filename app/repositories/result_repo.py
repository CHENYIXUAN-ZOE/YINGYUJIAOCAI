from __future__ import annotations

import contextlib
import json
from pathlib import Path

from app.core.config import Settings


class ResultRepository:
    def __init__(self, settings: Settings):
        self.base_dir = settings.result_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, job_id: str) -> Path:
        return self.base_dir / f"{job_id}.json"

    def save(self, job_id: str, payload: dict) -> dict:
        self._path(job_id).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    def get(self, job_id: str) -> dict | None:
        path = self._path(job_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def delete(self, job_id: str) -> None:
        with contextlib.suppress(FileNotFoundError):
            self._path(job_id).unlink()
