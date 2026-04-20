from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ReviewStatus


class ReviewItemRequest(BaseModel):
    review_status: ReviewStatus
    review_notes: str | None = None
    reviewer: str | None = None
    patched_fields: dict[str, Any] = Field(default_factory=dict)


class BatchReviewTarget(BaseModel):
    target_type: str
    target_id: str


class BatchReviewRequest(BaseModel):
    review_status: ReviewStatus
    targets: list[BatchReviewTarget]
    review_notes: str | None = None
    reviewer: str | None = None
