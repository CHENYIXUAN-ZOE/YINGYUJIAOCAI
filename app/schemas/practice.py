from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PracticeMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class PracticeChatRequest(BaseModel):
    job_id: str
    unit_id: str
    grade_band: str
    prompt_template: str
    final_prompt: str
    messages: list[PracticeMessage] = Field(default_factory=list)
    student_message: str | None = None
    is_opening_turn: bool = False
