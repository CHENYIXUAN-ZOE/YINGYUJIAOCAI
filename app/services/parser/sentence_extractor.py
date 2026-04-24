from __future__ import annotations

import re

from app.services.parser.heuristics import (
    classify_section_heading,
    infer_usage_note,
    looks_like_sentence_pattern,
    normalize_line,
    parse_speaker_line,
)

_ENGLISH_PREFIX_PATTERN = re.compile(r"^[A-Za-z0-9 ,.'?!\-…]+")


def _candidate_lines(unit: dict) -> list[str]:
    section_lines = unit.get("section_lines") or {}
    return list(section_lines.get("sentence_patterns") or unit.get("lines") or [])


def _extract_pattern_text(line: str) -> str | None:
    match = _ENGLISH_PREFIX_PATTERN.match(line)
    if not match:
        return None
    pattern = normalize_line(match.group(0)).rstrip(" ,")
    return pattern if pattern and len(pattern.split()) <= 14 else None


def extract(unit: dict) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    source_pages = list(unit.get("source_pages") or [1])

    for raw_line in _candidate_lines(unit):
        line = normalize_line(raw_line)
        if not line or classify_section_heading(line) or parse_speaker_line(line):
            continue
        if not looks_like_sentence_pattern(line):
            continue
        pattern = _extract_pattern_text(line)
        if not pattern:
            continue
        key = pattern.casefold()
        if key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "pattern": pattern,
                "usage_note": infer_usage_note(pattern),
                "examples": [pattern],
                "source_pages": source_pages,
                "source_excerpt": line,
            }
        )
    return items
