from __future__ import annotations

from app.services.parser.heuristics import (
    classify_section_heading,
    looks_like_sentence_pattern,
    looks_like_vocabulary_entry,
    normalize_line,
    parse_speaker_line,
)

SECTION_ORDER = ["vocabulary", "sentence_patterns", "dialogue_samples"]


def _infer_section_from_line(line: str) -> str | None:
    if parse_speaker_line(line):
        return "dialogue_samples"
    if looks_like_sentence_pattern(line):
        return "sentence_patterns"
    if looks_like_vocabulary_entry(line):
        return "vocabulary"
    return None


def classify(document: dict, units: list[dict]) -> list[dict]:
    for unit in units:
        section_lines = {name: [] for name in SECTION_ORDER}
        current_section: str | None = None
        for raw_line in unit.get("lines", []):
            line = normalize_line(raw_line)
            if not line:
                continue
            explicit_section = classify_section_heading(line)
            if explicit_section:
                current_section = explicit_section
                continue
            inferred_section = _infer_section_from_line(line)
            target_section = current_section or inferred_section
            if target_section:
                section_lines[target_section].append(line)

        unit["section_lines"] = {key: value for key, value in section_lines.items() if value}
        unit["sections"] = [section for section in SECTION_ORDER if unit["section_lines"].get(section)]
    return units
