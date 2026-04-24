from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import ParseStatus, ReviewStatus


class PdfPreflight(BaseModel):
    file_size_mb: float = 0
    page_count: int = 0
    text_layer_detected: bool = False
    detected_pdf_type: str = "unknown"
    estimated_duration_sec: int = 0
    estimated_duration_range: str | None = None
    duration_budget_sec: int = 600
    within_duration_budget: bool = True
    warnings: list[str] = Field(default_factory=list)


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
    preflight: PdfPreflight = Field(default_factory=PdfPreflight)


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
    preflight: PdfPreflight = Field(default_factory=PdfPreflight)
