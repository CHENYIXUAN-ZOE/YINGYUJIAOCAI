from __future__ import annotations

from pydantic import BaseModel

from app.schemas.common import ParseStatus, ReviewStatus


class ParseJob(BaseModel):
    job_id: str
    file_name: str
    file_path: str
    status: ParseStatus
    progress: int
    phase: str = "uploaded"
    phase_message: str | None = None
    page_total: int = 0
    page_done: int = 0
    unit_total: int = 0
    unit_done: int = 0
    retry_count: int = 0
    error_message: str | None = None
    last_error_code: str | None = None
    retryable: bool = False
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    updated_at: str | None = None
    review_status: ReviewStatus


class ParseRequest(BaseModel):
    force_reparse: bool = False


class JobStatusResponse(BaseModel):
    job_id: str
    file_name: str
    status: ParseStatus
    status_label: str
    progress: int
    phase: str
    phase_label: str
    phase_message: str | None = None
    page_total: int = 0
    page_done: int = 0
    unit_total: int = 0
    unit_done: int = 0
    retry_count: int = 0
    review_status: ReviewStatus
    error_message: str | None = None
    last_error_code: str | None = None
    retryable: bool = False
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    updated_at: str | None = None
