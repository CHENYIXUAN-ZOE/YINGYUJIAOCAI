from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.core.errors import AppError
from app.schemas.content import (
    Classification,
    DialogueSample,
    DialogueTurn,
    SentencePattern,
    UnitPackage,
    UnitPrompt,
    UnitTask,
    UnitRecord,
    VocabularyItem,
)
from app.services.generator import (
    dialogue_generator,
    prompt_builder,
    prompt_generator,
    sentence_generator,
    task_generator,
    vocabulary_generator,
)
from app.services.parser import dialogue_extractor, sentence_extractor, vocabulary_extractor

_UNIT_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "unit_theme": {"type": "STRING"},
        "vocabulary": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "word": {"type": "STRING"},
                    "part_of_speech": {"type": "STRING"},
                    "meaning_zh": {"type": "STRING"},
                    "example_sentences": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "source_excerpt": {"type": "STRING"},
                },
                "required": ["word", "part_of_speech", "meaning_zh", "example_sentences", "source_excerpt"],
            },
        },
        "sentence_patterns": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "pattern": {"type": "STRING"},
                    "usage_note": {"type": "STRING"},
                    "examples": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "source_excerpt": {"type": "STRING"},
                },
                "required": ["pattern", "usage_note", "examples", "source_excerpt"],
            },
        },
        "dialogue_samples": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING"},
                    "source_excerpt": {"type": "STRING"},
                    "turns": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "speaker": {"type": "STRING"},
                                "text_en": {"type": "STRING"},
                                "text_zh": {"type": "STRING"},
                            },
                            "required": ["speaker", "text_en", "text_zh"],
                        },
                    },
                },
                "required": ["title", "source_excerpt", "turns"],
            },
        },
        "unit_task": {
            "type": "OBJECT",
            "properties": {
                "task_intro": {"type": "STRING"},
                "source_basis": {"type": "ARRAY", "items": {"type": "STRING"}},
            },
            "required": ["task_intro", "source_basis"],
        },
        "unit_prompt": {
            "type": "OBJECT",
            "properties": {
                "unit_theme": {"type": "STRING"},
                "grammar_rules": {"type": "ARRAY", "items": {"type": "STRING"}},
                "prompt_notes": {"type": "ARRAY", "items": {"type": "STRING"}},
                "source_basis": {"type": "ARRAY", "items": {"type": "STRING"}},
            },
            "required": ["unit_theme", "grammar_rules", "prompt_notes", "source_basis"],
        },
    },
    "required": [
        "unit_theme",
        "vocabulary",
        "sentence_patterns",
        "dialogue_samples",
        "unit_task",
        "unit_prompt",
    ],
}


class UnitContentGenerator:
    def __init__(self, settings: Settings):
        self.settings = settings

    def build_unit_package(self, unit_record: UnitRecord, raw_unit: dict) -> UnitPackage:
        if self._vertex_ai_ready():
            return self._build_with_vertex_ai(unit_record, raw_unit)
        if self.settings.allow_placeholder_fallback:
            return self._build_with_fallback(unit_record, raw_unit)
        raise AppError(
            "API_GENERATION_REQUIRED",
            "external model API is required for content generation",
            status_code=500,
            details={"backend": "vertex_gemini"},
        )

    def _vertex_ai_ready(self) -> bool:
        return self.settings.resolve_google_credentials_path() is not None

    def _resolve_project_id(self, credentials_path: Path | None) -> str | None:
        if self.settings.google_cloud_project:
            return self.settings.google_cloud_project
        if not credentials_path or not credentials_path.exists():
            return None
        try:
            payload = json.loads(credentials_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        project_id = payload.get("project_id")
        return str(project_id) if project_id else None

    def _build_with_vertex_ai(self, unit_record: UnitRecord, raw_unit: dict) -> UnitPackage:
        credentials_path = self.settings.resolve_google_credentials_path()
        project_id = self._resolve_project_id(credentials_path)
        if not credentials_path or not credentials_path.exists() or not project_id:
            raise AppError(
                "VERTEX_CONFIG_INVALID",
                "Vertex AI credentials or project configuration is invalid",
                status_code=500,
            )

        try:
            from google import genai
            from google.genai import errors as genai_errors
            from google.genai import types
            from google.oauth2 import service_account
        except ImportError as exc:
            raise AppError(
                "GEMINI_SDK_MISSING",
                "google-genai dependency is missing; install requirements before using Gemini",
                status_code=500,
                details={"missing_module": str(exc)},
            ) from exc

        source_pages = raw_unit.get("source_pages", [1]) or [1]
        source_text = (raw_unit.get("text") or "").strip()
        if not source_text:
            source_text = "\n".join(raw_unit.get("lines", []))
        source_text = source_text[:12000]
        prompt = self._build_prompt(unit_record.classification, raw_unit, source_text)

        credentials = service_account.Credentials.from_service_account_file(
            str(credentials_path),
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        max_attempts = max(1, self.settings.gemini_max_retries)
        response = None
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            client = genai.Client(
                vertexai=True,
                project=project_id,
                location=self.settings.google_cloud_location,
                credentials=credentials,
                http_options=types.HttpOptions(api_version="v1"),
            )
            try:
                response = client.models.generate_content(
                    model=self.settings.gemini_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=_UNIT_RESPONSE_SCHEMA,
                        temperature=0.2,
                    ),
                )
                break
            except (genai_errors.APIError, OSError, TimeoutError) as exc:
                last_error = exc
                if attempt >= max_attempts:
                    error_details = {
                        "attempts": attempt,
                        "backend": "vertex_gemini",
                        "message": str(exc),
                    }
                    if isinstance(exc, genai_errors.APIError):
                        error_details["code"] = exc.code
                    raise AppError(
                        "GEMINI_REQUEST_FAILED",
                        "Gemini request failed",
                        status_code=502,
                        details=error_details,
                    ) from exc
                time.sleep(min(2 * attempt, 5))
            finally:
                client.close()

        if response is None:
            raise AppError(
                "GEMINI_REQUEST_FAILED",
                "Gemini request failed",
                status_code=502,
                details={"backend": "vertex_gemini", "message": str(last_error) if last_error else "unknown"},
            )

        try:
            payload = json.loads(response.text)
        except json.JSONDecodeError as exc:
            raise AppError(
                "GEMINI_INVALID_JSON",
                "Gemini returned invalid JSON",
                status_code=502,
            ) from exc

        try:
            return self._payload_to_unit_package(unit_record, source_pages, payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise AppError(
                "GEMINI_SCHEMA_MISMATCH",
                "Gemini returned an unexpected schema",
                status_code=502,
                details={"error": str(exc)},
            ) from exc

    def _build_with_fallback(self, unit_record: UnitRecord, raw_unit: dict) -> UnitPackage:
        classification = unit_record.classification
        unit_id = unit_record.unit_id
        vocabulary = vocabulary_generator.generate(
            classification,
            vocabulary_extractor.extract(raw_unit),
            unit_id,
        )
        sentence_patterns = sentence_generator.generate(
            classification,
            sentence_extractor.extract(raw_unit),
            unit_id,
        )
        dialogue_samples = dialogue_generator.generate(
            classification,
            dialogue_extractor.extract(raw_unit),
            unit_id,
        )

        return UnitPackage(
            unit=unit_record,
            vocabulary=vocabulary,
            sentence_patterns=sentence_patterns,
            dialogue_samples=dialogue_samples,
            unit_task=task_generator.generate(classification, unit_id),
            unit_prompt=prompt_generator.generate(classification, unit_id),
        )

    def _payload_to_unit_package(self, unit_record: UnitRecord, source_pages: list[int], payload: dict[str, Any]) -> UnitPackage:
        classification = unit_record.classification
        unit_id = unit_record.unit_id
        unit_record.unit_theme = payload.get("unit_theme") or unit_record.unit_theme

        vocabulary = [
            VocabularyItem(
                item_id=f"{unit_id}_voc_{index}",
                classification=classification,
                word=item["word"].strip(),
                part_of_speech=item.get("part_of_speech"),
                meaning_zh=item.get("meaning_zh"),
                example_sentences=[sentence.strip() for sentence in item.get("example_sentences", []) if sentence.strip()],
                source_pages=source_pages,
                source_excerpt=item.get("source_excerpt"),
            )
            for index, item in enumerate(payload.get("vocabulary", []), start=1)
            if item.get("word")
        ]

        sentence_patterns = [
            SentencePattern(
                item_id=f"{unit_id}_sp_{index}",
                classification=classification,
                pattern=item["pattern"].strip(),
                usage_note=item.get("usage_note"),
                examples=[example.strip() for example in item.get("examples", []) if example.strip()],
                source_pages=source_pages,
                source_excerpt=item.get("source_excerpt"),
            )
            for index, item in enumerate(payload.get("sentence_patterns", []), start=1)
            if item.get("pattern")
        ]

        dialogue_samples = [
            DialogueSample(
                item_id=f"{unit_id}_dlg_{index}",
                classification=classification,
                title=item.get("title"),
                turns=[
                    DialogueTurn(
                        turn_index=turn_index,
                        speaker=turn["speaker"].strip(),
                        text_en=turn["text_en"].strip(),
                        text_zh=turn["text_zh"].strip(),
                    )
                    for turn_index, turn in enumerate(item.get("turns", []), start=1)
                    if turn.get("speaker") and turn.get("text_en") and turn.get("text_zh")
                ],
                source_pages=source_pages,
                source_excerpt=item.get("source_excerpt"),
            )
            for index, item in enumerate(payload.get("dialogue_samples", []), start=1)
        ]

        if not vocabulary or not sentence_patterns or not dialogue_samples:
            raise ValueError("empty structured sections are not allowed")

        return UnitPackage(
            unit=unit_record,
            vocabulary=vocabulary,
            sentence_patterns=sentence_patterns,
            dialogue_samples=dialogue_samples,
            unit_task=UnitTask(
                item_id=f"{unit_id}_task_1",
                classification=classification,
                task_intro=payload["unit_task"]["task_intro"].strip(),
                source_basis=[item.strip() for item in payload["unit_task"].get("source_basis", []) if item.strip()],
            ),
            unit_prompt=UnitPrompt(
                item_id=f"{unit_id}_prompt_1",
                classification=classification,
                unit_theme=payload["unit_prompt"]["unit_theme"].strip(),
                grammar_rules=[item.strip() for item in payload["unit_prompt"].get("grammar_rules", []) if item.strip()],
                prompt_notes=[item.strip() for item in payload["unit_prompt"].get("prompt_notes", []) if item.strip()],
                source_basis=[item.strip() for item in payload["unit_prompt"].get("source_basis", []) if item.strip()],
            ),
        )

    def _build_prompt(self, classification: Classification, raw_unit: dict, source_text: str) -> str:
        return prompt_builder.build_unit_generation_prompt(classification, raw_unit, source_text)
