from __future__ import annotations

import contextlib
import json
from pathlib import Path

from app.core.config import Settings


class ExportRepository:
    def __init__(self, settings: Settings):
        self.base_dir = settings.export_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def metadata_path(self, export_id: str) -> Path:
        return self.base_dir / f"{export_id}.meta.json"

    def _legacy_metadata_path(self, export_id: str) -> Path:
        return self.base_dir / f"{export_id}.json"

    def _is_metadata_payload(self, payload: dict) -> bool:
        return {"export_id", "job_id", "format", "download_url"}.issubset(payload.keys())

    def save_metadata(self, export_id: str, payload: dict) -> dict:
        self.metadata_path(export_id).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return payload

    def get_metadata(self, export_id: str) -> dict | None:
        for path in [self.metadata_path(export_id), self._legacy_metadata_path(export_id)]:
            if not path.exists():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and self._is_metadata_payload(payload):
                return payload
        return None

    def list_metadata(self) -> list[dict]:
        records: list[dict] = []
        seen_export_ids: set[str] = set()
        for path in sorted(self.base_dir.glob("exp_*.meta.json"), reverse=True):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or not self._is_metadata_payload(payload):
                continue
            seen_export_ids.add(payload["export_id"])
            records.append(payload)
        for path in sorted(self.base_dir.glob("exp_*.json"), reverse=True):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or not self._is_metadata_payload(payload):
                continue
            if payload["export_id"] in seen_export_ids:
                continue
            records.append(payload)
        return records

    def delete_export(self, export_id: str) -> None:
        metadata = self.get_metadata(export_id)
        if metadata and metadata.get("file_path"):
            with contextlib.suppress(FileNotFoundError):
                Path(metadata["file_path"]).unlink()
        with contextlib.suppress(FileNotFoundError):
            self.metadata_path(export_id).unlink()
        with contextlib.suppress(FileNotFoundError):
            self._legacy_metadata_path(export_id).unlink()

    def delete_exports_for_job(self, job_id: str) -> None:
        for metadata in self.list_metadata():
            if metadata.get("job_id") != job_id:
                continue
            export_id = metadata.get("export_id")
            if export_id:
                self.delete_export(export_id)
