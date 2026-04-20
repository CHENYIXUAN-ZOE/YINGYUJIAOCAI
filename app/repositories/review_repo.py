from __future__ import annotations

import json
from pathlib import Path

from app.core.config import Settings


class ReviewRepository:
    def __init__(self, settings: Settings):
        self.base_dir = settings.review_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, job_id: str) -> Path:
        return self.base_dir / f"{job_id}.json"

    def save(self, job_id: str, records: list[dict]) -> list[dict]:
        self._path(job_id).write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        return records

    def get(self, job_id: str) -> list[dict]:
        path = self._path(job_id)
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8"))
