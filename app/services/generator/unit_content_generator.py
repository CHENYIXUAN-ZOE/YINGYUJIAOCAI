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
from app.services.parser.heuristics import normalize_line, parse_speaker_line
from app.services.parser import dialogue_extractor, sentence_extractor, vocabulary_extractor

_RECOVERABLE_MODEL_CODES = {
    "GEMINI_REQUEST_FAILED",
    "GEMINI_INVALID_JSON",
    "GEMINI_SCHEMA_MISMATCH",
}

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
            try:
                return self._build_with_vertex_ai(unit_record, raw_unit)
            except AppError as exc:
                if self._should_use_unit_fallback(exc):
                    return self._build_with_fallback(unit_record, raw_unit)
                raise
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
            payload = self._load_model_payload(response.text)
        except json.JSONDecodeError as exc:
            raise AppError(
                "GEMINI_INVALID_JSON",
                "Gemini returned invalid JSON",
                status_code=502,
            ) from exc

        repaired_payload = self._repair_model_payload(unit_record, raw_unit, payload)
        try:
            return self._payload_to_unit_package(unit_record, source_pages, repaired_payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise AppError(
                "GEMINI_SCHEMA_MISMATCH",
                "Gemini returned an unexpected schema",
                status_code=502,
                details={"error": str(exc)},
            ) from exc

    def _should_use_unit_fallback(self, exc: AppError) -> bool:
        return exc.code in _RECOVERABLE_MODEL_CODES

    def _build_with_fallback(self, unit_record: UnitRecord, raw_unit: dict) -> UnitPackage:
        classification = unit_record.classification
        unit_id = unit_record.unit_id
        extracted_vocabulary = vocabulary_extractor.extract(raw_unit)
        extracted_sentence_patterns = sentence_extractor.extract(raw_unit)
        extracted_dialogues = dialogue_extractor.extract(raw_unit)
        vocabulary = vocabulary_generator.generate(
            classification,
            extracted_vocabulary,
            unit_id,
        )
        sentence_patterns = sentence_generator.generate(
            classification,
            extracted_sentence_patterns,
            unit_id,
        )
        dialogue_samples = dialogue_generator.generate(
            classification,
            extracted_dialogues,
            unit_id,
        )

        return UnitPackage(
            unit=unit_record,
            vocabulary=vocabulary,
            sentence_patterns=sentence_patterns,
            dialogue_samples=dialogue_samples,
            unit_task=task_generator.generate(
                classification,
                unit_id,
                unit_theme=raw_unit.get("unit_theme"),
                vocabulary=vocabulary,
                sentence_patterns=sentence_patterns,
            ),
            unit_prompt=prompt_generator.generate(
                classification,
                unit_id,
                unit_theme=raw_unit.get("unit_theme"),
                vocabulary=vocabulary,
                sentence_patterns=sentence_patterns,
                dialogue_samples=dialogue_samples,
            ),
        )

    def _payload_to_unit_package(self, unit_record: UnitRecord, source_pages: list[int], payload: dict[str, Any]) -> UnitPackage:
        classification = unit_record.classification
        unit_id = unit_record.unit_id
        unit_record.unit_theme = self._clean_model_text(payload.get("unit_theme")) or unit_record.unit_theme

        vocabulary = [
            VocabularyItem(
                item_id=f"{unit_id}_voc_{index}",
                classification=classification,
                word=self._clean_model_text(item["word"]),
                part_of_speech=self._clean_model_text(item.get("part_of_speech")),
                meaning_zh=self._clean_model_text(item.get("meaning_zh")),
                example_sentences=[
                    self._clean_model_text(sentence)
                    for sentence in item.get("example_sentences", [])
                    if self._clean_model_text(sentence)
                ],
                source_pages=source_pages,
                source_excerpt=self._clean_model_text(item.get("source_excerpt")),
            )
            for index, item in enumerate(payload.get("vocabulary", []), start=1)
            if item.get("word")
        ]

        sentence_patterns = [
            SentencePattern(
                item_id=f"{unit_id}_sp_{index}",
                classification=classification,
                pattern=self._clean_model_text(item["pattern"]),
                usage_note=self._clean_model_text(item.get("usage_note")),
                examples=[
                    self._clean_model_text(example)
                    for example in item.get("examples", [])
                    if self._clean_model_text(example)
                ],
                source_pages=source_pages,
                source_excerpt=self._clean_model_text(item.get("source_excerpt")),
            )
            for index, item in enumerate(payload.get("sentence_patterns", []), start=1)
            if item.get("pattern")
        ]

        dialogue_samples = [
            DialogueSample(
                item_id=f"{unit_id}_dlg_{index}",
                classification=classification,
                title=self._clean_model_text(item.get("title")),
                turns=[
                    DialogueTurn(
                        turn_index=turn_index,
                        speaker=turn["speaker"],
                        text_en=turn["text_en"],
                        text_zh=turn["text_zh"],
                    )
                    for turn_index, turn in enumerate(self._normalize_dialogue_turns(item.get("turns", [])), start=1)
                ],
                source_pages=source_pages,
                source_excerpt=self._clean_model_text(item.get("source_excerpt")),
            )
            for index, item in enumerate(payload.get("dialogue_samples", []), start=1)
            if self._normalize_dialogue_turns(item.get("turns", []))
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
                task_intro=self._clean_model_text(payload["unit_task"]["task_intro"]),
                source_basis=[
                    self._clean_model_text(item)
                    for item in payload["unit_task"].get("source_basis", [])
                    if self._clean_model_text(item)
                ],
            ),
            unit_prompt=UnitPrompt(
                item_id=f"{unit_id}_prompt_1",
                classification=classification,
                unit_theme=self._clean_model_text(payload["unit_prompt"]["unit_theme"]),
                grammar_rules=[
                    self._clean_model_text(item)
                    for item in payload["unit_prompt"].get("grammar_rules", [])
                    if self._clean_model_text(item)
                ],
                prompt_notes=[
                    self._clean_model_text(item)
                    for item in payload["unit_prompt"].get("prompt_notes", [])
                    if self._clean_model_text(item)
                ],
                source_basis=[
                    self._clean_model_text(item)
                    for item in payload["unit_prompt"].get("source_basis", [])
                    if self._clean_model_text(item)
                ],
            ),
        )

    def _load_model_payload(self, response_text: str) -> dict[str, Any]:
        text = (response_text or "").strip()
        candidates = [text]
        if text.startswith("```"):
            stripped = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
            stripped = re.sub(r"\s*```$", "", stripped)
            candidates.append(stripped.strip())
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            candidates.append(text[first_brace : last_brace + 1].strip())

        last_error: json.JSONDecodeError | None = None
        for candidate in candidates:
            if not candidate:
                continue
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError as exc:
                last_error = exc
                continue
            if isinstance(payload, dict):
                return payload
        if last_error is not None:
            raise last_error
        raise json.JSONDecodeError("empty json payload", text, 0)

    def _repair_model_payload(self, unit_record: UnitRecord, raw_unit: dict, payload: dict[str, Any]) -> dict[str, Any]:
        root = payload if isinstance(payload, dict) else {}
        fallback_payload: dict[str, Any] | None = None

        def ensure_fallback_payload() -> dict[str, Any]:
            nonlocal fallback_payload
            if fallback_payload is None:
                fallback_payload = self._unit_package_to_payload(self._build_with_fallback(unit_record, raw_unit))
            return fallback_payload

        fallback_theme = (
            self._clean_model_text(raw_unit.get("unit_theme"))
            or unit_record.unit_theme
            or unit_record.classification.unit_name
            or unit_record.classification.unit_code
        )

        vocabulary = self._repair_vocabulary_section(root.get("vocabulary"))
        if not vocabulary:
            vocabulary = ensure_fallback_payload()["vocabulary"]

        sentence_patterns = self._repair_sentence_pattern_section(root.get("sentence_patterns"))
        if not sentence_patterns:
            sentence_patterns = ensure_fallback_payload()["sentence_patterns"]

        dialogue_samples = self._repair_dialogue_section(root.get("dialogue_samples"))
        if not dialogue_samples:
            dialogue_samples = ensure_fallback_payload()["dialogue_samples"]

        unit_task = self._repair_unit_task_section(root.get("unit_task"), fallback_theme)
        if not unit_task:
            unit_task = ensure_fallback_payload()["unit_task"]

        unit_prompt = self._repair_unit_prompt_section(root.get("unit_prompt"), fallback_theme)
        if not unit_prompt:
            unit_prompt = ensure_fallback_payload()["unit_prompt"]

        return {
            "unit_theme": self._clean_model_text(root.get("unit_theme")) or fallback_theme,
            "vocabulary": vocabulary,
            "sentence_patterns": sentence_patterns,
            "dialogue_samples": dialogue_samples,
            "unit_task": unit_task,
            "unit_prompt": unit_prompt,
        }

    def _unit_package_to_payload(self, package: UnitPackage) -> dict[str, Any]:
        return {
            "unit_theme": package.unit.unit_theme or package.unit_prompt.unit_theme,
            "vocabulary": [
                {
                    "word": item.word,
                    "part_of_speech": item.part_of_speech or "",
                    "meaning_zh": item.meaning_zh or "",
                    "example_sentences": item.example_sentences,
                    "source_excerpt": item.source_excerpt or "",
                }
                for item in package.vocabulary
            ],
            "sentence_patterns": [
                {
                    "pattern": item.pattern,
                    "usage_note": item.usage_note or "",
                    "examples": item.examples,
                    "source_excerpt": item.source_excerpt or "",
                }
                for item in package.sentence_patterns
            ],
            "dialogue_samples": [
                {
                    "title": item.title or "",
                    "source_excerpt": item.source_excerpt or "",
                    "turns": [
                        {
                            "speaker": turn.speaker,
                            "text_en": turn.text_en,
                            "text_zh": turn.text_zh,
                        }
                        for turn in item.turns
                    ],
                }
                for item in package.dialogue_samples
            ],
            "unit_task": {
                "task_intro": package.unit_task.task_intro,
                "source_basis": package.unit_task.source_basis,
            },
            "unit_prompt": {
                "unit_theme": package.unit_prompt.unit_theme,
                "grammar_rules": package.unit_prompt.grammar_rules,
                "prompt_notes": package.unit_prompt.prompt_notes,
                "source_basis": package.unit_prompt.source_basis,
            },
        }

    def _repair_vocabulary_section(self, payload: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for item in self._ensure_list(payload):
            if isinstance(item, str):
                word = self._clean_model_text(item)
                if not word:
                    continue
                items.append(
                    {
                        "word": word,
                        "part_of_speech": "",
                        "meaning_zh": "",
                        "example_sentences": [],
                        "source_excerpt": word,
                    }
                )
                continue
            if not isinstance(item, dict):
                continue
            word = self._clean_model_text(item.get("word") or item.get("term") or item.get("text"))
            if not word:
                continue
            example_sentences = self._clean_string_list(
                item.get("example_sentences") or item.get("examples") or item.get("example")
            )
            items.append(
                {
                    "word": word,
                    "part_of_speech": self._clean_model_text(item.get("part_of_speech") or item.get("pos") or item.get("partOfSpeech")),
                    "meaning_zh": self._clean_model_text(item.get("meaning_zh") or item.get("meaning") or item.get("translation") or item.get("meaning_cn")),
                    "example_sentences": example_sentences,
                    "source_excerpt": self._clean_model_text(item.get("source_excerpt") or item.get("source") or item.get("excerpt")) or word,
                }
            )
        return items

    def _repair_sentence_pattern_section(self, payload: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for item in self._ensure_list(payload):
            if isinstance(item, str):
                pattern = self._clean_model_text(item)
                if not pattern:
                    continue
                items.append(
                    {
                        "pattern": pattern,
                        "usage_note": "",
                        "examples": [],
                        "source_excerpt": pattern,
                    }
                )
                continue
            if not isinstance(item, dict):
                continue
            pattern = self._clean_model_text(item.get("pattern") or item.get("sentence") or item.get("text"))
            if not pattern:
                continue
            items.append(
                {
                    "pattern": pattern,
                    "usage_note": self._clean_model_text(item.get("usage_note") or item.get("note")),
                    "examples": self._clean_string_list(item.get("examples") or item.get("example_sentences") or item.get("example")),
                    "source_excerpt": self._clean_model_text(item.get("source_excerpt") or item.get("source") or item.get("excerpt")) or pattern,
                }
            )
        return items

    def _repair_dialogue_section(self, payload: Any) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for item in self._ensure_list(payload):
            if isinstance(item, str):
                turns = self._repair_dialogue_turns(item)
                if not turns:
                    continue
                items.append(
                    {
                        "title": "Dialogue",
                        "source_excerpt": item,
                        "turns": turns,
                    }
                )
                continue
            if not isinstance(item, dict):
                continue
            turns = self._repair_dialogue_turns(
                item.get("turns")
                or item.get("dialogue")
                or item.get("lines")
                or item.get("content")
            )
            if not turns:
                continue
            source_excerpt = self._clean_model_text(item.get("source_excerpt") or item.get("source") or item.get("excerpt"))
            if not source_excerpt:
                source_excerpt = " ".join(turn["text_en"] for turn in turns[:2])
            items.append(
                {
                    "title": self._clean_model_text(item.get("title") or item.get("name")) or "Dialogue",
                    "source_excerpt": source_excerpt,
                    "turns": turns,
                }
            )
        return items

    def _repair_unit_task_section(self, payload: Any, fallback_theme: str) -> dict[str, Any] | None:
        if isinstance(payload, str):
            task_intro = self._clean_model_text(payload)
            if task_intro:
                return {"task_intro": task_intro, "source_basis": [fallback_theme]}
            return None
        if not isinstance(payload, dict):
            return None
        task_intro = self._clean_model_text(payload.get("task_intro") or payload.get("intro") or payload.get("task"))
        if not task_intro:
            return None
        return {
            "task_intro": task_intro,
            "source_basis": self._clean_string_list(payload.get("source_basis") or payload.get("basis")) or [fallback_theme],
        }

    def _repair_unit_prompt_section(self, payload: Any, fallback_theme: str) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        unit_theme = self._clean_model_text(payload.get("unit_theme") or payload.get("theme")) or fallback_theme
        grammar_rules = self._clean_string_list(payload.get("grammar_rules") or payload.get("rules"))
        prompt_notes = self._clean_string_list(payload.get("prompt_notes") or payload.get("notes"))
        source_basis = self._clean_string_list(payload.get("source_basis") or payload.get("basis"))
        if not unit_theme:
            return None
        return {
            "unit_theme": unit_theme,
            "grammar_rules": grammar_rules,
            "prompt_notes": prompt_notes,
            "source_basis": source_basis or [fallback_theme],
        }

    def _repair_dialogue_turns(self, payload: Any) -> list[dict[str, str]]:
        normalized_turns: list[dict[str, str]] = []
        for item in self._ensure_list(payload):
            if isinstance(item, str):
                speaker_line = parse_speaker_line(item)
                if not speaker_line:
                    continue
                speaker, text_en = speaker_line
                normalized_turn = {
                    "speaker": self._clean_model_text(speaker),
                    "text_en": self._clean_model_text(text_en),
                    "text_zh": self._clean_model_text(text_en),
                }
            elif isinstance(item, dict):
                speaker = self._clean_model_text(item.get("speaker") or item.get("role") or item.get("name"))
                text_en = self._clean_model_text(item.get("text_en") or item.get("text") or item.get("content") or item.get("en"))
                text_zh = self._clean_model_text(item.get("text_zh") or item.get("zh") or item.get("translation")) or text_en
                normalized_turn = {
                    "speaker": speaker,
                    "text_en": text_en,
                    "text_zh": text_zh,
                }
            else:
                continue

            if not normalized_turn["speaker"] or not normalized_turn["text_en"] or not normalized_turn["text_zh"]:
                continue
            if normalized_turns and normalized_turns[-1] == normalized_turn:
                continue
            normalized_turns.append(normalized_turn)
            if len(normalized_turns) >= 12:
                break
        return normalized_turns

    def _ensure_list(self, value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        if isinstance(value, str):
            lines = [normalize_line(line) for line in value.splitlines() if normalize_line(line)]
            return lines or [value]
        return [value]

    def _clean_string_list(self, value: Any) -> list[str]:
        return [cleaned for item in self._ensure_list(value) if (cleaned := self._clean_model_text(item))]

    def _clean_model_text(self, value: Any) -> str:
        return normalize_line(str(value or ""))

    def _normalize_dialogue_turns(self, turns: list[dict[str, Any]]) -> list[dict[str, str]]:
        normalized_turns: list[dict[str, str]] = []
        for turn in turns:
            speaker = self._clean_model_text(turn.get("speaker"))
            text_en = self._clean_model_text(turn.get("text_en"))
            text_zh = self._clean_model_text(turn.get("text_zh"))
            if not speaker or not text_en or not text_zh:
                continue
            normalized_turn = {
                "speaker": speaker,
                "text_en": text_en,
                "text_zh": text_zh,
            }
            if normalized_turns and normalized_turns[-1] == normalized_turn:
                continue
            normalized_turns.append(normalized_turn)
            if len(normalized_turns) >= 12:
                break
        return normalized_turns

    def _build_prompt(self, classification: Classification, raw_unit: dict, source_text: str) -> str:
        return prompt_builder.build_unit_generation_prompt(classification, raw_unit, source_text)
