from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ParseStatus(str, Enum):
    uploaded = "uploaded"
    queued = "queued"
    parsing = "parsing"
    structuring = "structuring"
    generating = "generating"
    reviewing = "reviewing"
    completed = "completed"
    failed = "failed"


class ReviewStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    revised = "revised"


class GenerationMode(str, Enum):
    extracted = "extracted"
    normalized = "normalized"
    derived = "derived"
    manual = "manual"


class ContentTargetType(str, Enum):
    book = "book"
    unit = "unit"
    vocabulary_item = "vocabulary_item"
    sentence_pattern = "sentence_pattern"
    dialogue_sample = "dialogue_sample"
    unit_task = "unit_task"
    unit_prompt = "unit_prompt"


class ApiErrorPayload(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ApiResponse(BaseModel):
    success: bool = True
    data: Any
    message: str = "ok"


class ErrorResponse(BaseModel):
    success: bool = False
    error: ApiErrorPayload
