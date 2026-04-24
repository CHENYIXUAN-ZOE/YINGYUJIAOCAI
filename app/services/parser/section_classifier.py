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


def _estimate_section_confidence(
    *,
    section_lines: dict[str, list[str]],
    recognized_line_count: int,
    content_line_count: int,
    explicit_heading_hits: int,
) -> float:
    section_count = sum(1 for lines in section_lines.values() if lines)
    coverage = recognized_line_count / max(content_line_count, 1)
    confidence = 0.18
    if section_count >= 2:
        confidence = 0.82
    elif section_count == 1:
        confidence = 0.58
    if coverage >= 0.45:
        confidence += 0.08
    elif coverage < 0.12:
        confidence -= 0.12
    if explicit_heading_hits:
        confidence += 0.06
    return round(max(0.05, min(0.98, confidence)), 3)


def classify(document: dict, units: list[dict]) -> list[dict]:
    for unit in units:
        section_lines = {name: [] for name in SECTION_ORDER}
        current_section: str | None = None
        explicit_heading_hits = 0
        content_line_count = 0
        for raw_line in unit.get("lines", []):
            line = normalize_line(raw_line)
            if not line:
                continue
            explicit_section = classify_section_heading(line)
            if explicit_section:
                current_section = explicit_section
                explicit_heading_hits += 1
                continue
            content_line_count += 1
            inferred_section = _infer_section_from_line(line)
            target_section = current_section or inferred_section
            if target_section:
                section_lines[target_section].append(line)

        unit["section_lines"] = {key: value for key, value in section_lines.items() if value}
        unit["sections"] = [section for section in SECTION_ORDER if unit["section_lines"].get(section)]
        recognized_line_count = sum(len(lines) for lines in unit["section_lines"].values())
        unit["section_confidence"] = _estimate_section_confidence(
            section_lines=unit["section_lines"],
            recognized_line_count=recognized_line_count,
            content_line_count=content_line_count,
            explicit_heading_hits=explicit_heading_hits,
        )
        unit["section_stats"] = {
            "recognized_line_count": recognized_line_count,
            "content_line_count": content_line_count,
            "explicit_heading_hits": explicit_heading_hits,
        }
    return units


def assess_classification(document: dict, units: list[dict]) -> dict:
    page_count = int(document.get("page_count") or len(document.get("pages") or []) or 1)
    warnings: list[str] = []
    low_confidence_reasons: list[str] = []
    if not units:
        low_confidence_reasons.append("no_units_to_classify")

    substantial_units = 0
    units_with_sections = 0
    recognized_lines = 0
    content_lines = 0
    low_confidence_units = 0

    for unit in units:
        unit_lines = [normalize_line(line) for line in unit.get("lines", []) if normalize_line(line)]
        if len(unit_lines) >= 8:
            substantial_units += 1
        if unit.get("sections"):
            units_with_sections += 1
        stats = unit.get("section_stats") or {}
        recognized_lines += int(stats.get("recognized_line_count", 0))
        content_lines += int(stats.get("content_line_count", 0))
        if float(unit.get("section_confidence", 0.0)) < 0.4:
            low_confidence_units += 1

    section_coverage = recognized_lines / max(content_lines, 1)
    if page_count >= 12 and units and units_with_sections == 0:
        low_confidence_reasons.append("no_sections_detected")
    if substantial_units >= 2 and low_confidence_units >= max(2, substantial_units // 2 + 1):
        low_confidence_reasons.append("most_substantial_units_lack_section_signals")
    if page_count >= 24 and section_coverage < 0.08 and substantial_units >= 2:
        warnings.append("very_low_section_coverage")
        low_confidence_reasons.append("section_coverage_too_low")

    confidence = round(
        max(
            0.05,
            min(
                1.0,
                0.84
                - 0.22 * len(low_confidence_reasons)
                - 0.05 * len(warnings)
                - 0.04 * low_confidence_units,
            ),
        ),
        3,
    )
    return {
        "unit_count": len(units),
        "page_count": page_count,
        "substantial_units": substantial_units,
        "units_with_sections": units_with_sections,
        "low_confidence_units": low_confidence_units,
        "section_coverage": round(section_coverage, 3),
        "warnings": warnings,
        "low_confidence_reasons": low_confidence_reasons,
        "low_confidence": bool(low_confidence_reasons),
        "confidence": confidence,
    }
