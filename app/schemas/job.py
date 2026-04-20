from __future__ import annotations

from pydantic import BaseModel

from app.schemas.common import ParseStatus, ReviewStatus


class ParseJob(BaseModel):
    job_id: str
    file_name: str
    file_path: str
    status: ParseStatus
    progress: int
    error_message: str | None = None
    created_at: str
    finished_at: str | None = None
    review_status: ReviewStatus


class ParseRequest(BaseModel):
    force_reparse: bool = False


class JobStatusResponse(BaseModel):
    job_id: str
    status: ParseStatus
    progress: int
    review_status: ReviewStatus
    error_message: str | None = None
    created_at: str
    finished_at: str | None = None
