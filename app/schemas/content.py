from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import GenerationMode, ReviewStatus


class Classification(BaseModel):
    textbook_version: str
    textbook_name: str
    unit_code: str
    unit_name: str


class Book(BaseModel):
    book_id: str
    textbook_version: str
    textbook_name: str
    publisher: str | None = None
    grade: str | None = None
    term: str | None = None
    source_job_id: str
    source_pages: list[int] = Field(default_factory=list)
    confidence: float = 1.0
    review_status: ReviewStatus = ReviewStatus.pending


class UnitRecord(BaseModel):
    unit_id: str
    classification: Classification
    unit_theme: str | None = None
    source_pages: list[int] = Field(default_factory=list)
    confidence: float = 1.0
    review_status: ReviewStatus = ReviewStatus.pending


class VocabularyItem(BaseModel):
    item_id: str
    classification: Classification
    word: str
    part_of_speech: str | None = None
    meaning_zh: str | None = None
    example_sentences: list[str] = Field(default_factory=list)
    source_pages: list[int] = Field(default_factory=list)
    source_excerpt: str | None = None
    confidence: float = 1.0
    generation_mode: GenerationMode = GenerationMode.normalized
    review_status: ReviewStatus = ReviewStatus.pending


class SentencePattern(BaseModel):
    item_id: str
    classification: Classification
    pattern: str
    usage_note: str | None = None
    examples: list[str] = Field(default_factory=list)
    source_pages: list[int] = Field(default_factory=list)
    source_excerpt: str | None = None
    confidence: float = 1.0
    generation_mode: GenerationMode = GenerationMode.normalized
    review_status: ReviewStatus = ReviewStatus.pending


class DialogueTurn(BaseModel):
    turn_index: int
    speaker: str
    text_en: str
    text_zh: str


class DialogueSample(BaseModel):
    item_id: str
    classification: Classification
    title: str | None = None
    turns: list[DialogueTurn] = Field(default_factory=list)
    source_pages: list[int] = Field(default_factory=list)
    source_excerpt: str | None = None
    confidence: float = 1.0
    generation_mode: GenerationMode = GenerationMode.derived
    review_status: ReviewStatus = ReviewStatus.pending


class UnitTask(BaseModel):
    item_id: str
    classification: Classification
    task_intro: str
    source_basis: list[str] = Field(default_factory=list)
    confidence: float = 1.0
    generation_mode: GenerationMode = GenerationMode.derived
    review_status: ReviewStatus = ReviewStatus.pending


class UnitPrompt(BaseModel):
    item_id: str
    classification: Classification
    unit_theme: str
    grammar_rules: list[str] = Field(default_factory=list)
    prompt_notes: list[str] = Field(default_factory=list)
    source_basis: list[str] = Field(default_factory=list)
    confidence: float = 1.0
    generation_mode: GenerationMode = GenerationMode.derived
    review_status: ReviewStatus = ReviewStatus.pending


class ReviewRecord(BaseModel):
    review_id: str
    target_type: str
    target_id: str
    review_status: ReviewStatus
    review_notes: str | None = None
    reviewer: str | None = None
    reviewed_at: str | None = None


class ExportMeta(BaseModel):
    schema_version: str = "v1"
    export_scope: str = "book"
    approved_only: bool = True
    exported_at: str | None = None
    exported_by: str | None = None
    unit_ids: list[str] = Field(default_factory=list)


class UnitPackage(BaseModel):
    unit: UnitRecord
    vocabulary: list[VocabularyItem] = Field(default_factory=list)
    sentence_patterns: list[SentencePattern] = Field(default_factory=list)
    dialogue_samples: list[DialogueSample] = Field(default_factory=list)
    unit_task: UnitTask
    unit_prompt: UnitPrompt


class StructuredContent(BaseModel):
    job: dict
    book: Book
    units: list[UnitPackage]
    review_records: list[ReviewRecord] = Field(default_factory=list)
    export_meta: ExportMeta
