from __future__ import annotations

import contextlib
from pathlib import Path

from app.core.config import Settings
from app.schemas.job import ParseJob


class JobRepository:
    def __init__(self, settings: Settings):
        self.base_dir = settings.job_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, job_id: str) -> Path:
        return self.base_dir / f"{job_id}.json"

    def save(self, job: ParseJob) -> ParseJob:
        self._path(job.job_id).write_text(job.model_dump_json(indent=2), encoding="utf-8")
        return job

    def get(self, job_id: str) -> ParseJob | None:
        path = self._path(job_id)
        if not path.exists():
            return None
        return ParseJob.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self) -> list[ParseJob]:
        jobs: list[ParseJob] = []
        for path in sorted(self.base_dir.glob("*.json"), reverse=True):
            jobs.append(ParseJob.model_validate_json(path.read_text(encoding="utf-8")))
        return jobs

    def delete(self, job_id: str) -> None:
        with contextlib.suppress(FileNotFoundError):
            self._path(job_id).unlink()
