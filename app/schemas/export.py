from __future__ import annotations

from pydantic import BaseModel, Field


class ExportRequest(BaseModel):
    job_id: str
    export_scope: str = "book"
    approved_only: bool = True
    format: str = "json"
    unit_ids: list[str] = Field(default_factory=list)


class ExportResponse(BaseModel):
    export_id: str
    status: str
    download_url: str
