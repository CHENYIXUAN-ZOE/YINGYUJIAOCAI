from __future__ import annotations

import re

from app.services.parser.heuristics import (
    classify_section_heading,
    looks_like_vocabulary_entry,
    normalize_line,
    parse_speaker_line,
)

_POS_PATTERN = re.compile(r"\b(n|v|adj|adv|prep|conj|pron|num|art|aux)\.?\b", re.IGNORECASE)
_WORD_PATTERN = re.compile(r"^([A-Za-z][A-Za-z' -]{0,40})")
_CHINESE_PATTERN = re.compile(r"[\u4e00-\u9fff][\u4e00-\u9fff0-9、，,；;（）() ]*")


def _candidate_lines(unit: dict) -> list[str]:
    section_lines = unit.get("section_lines") or {}
    return list(section_lines.get("vocabulary") or unit.get("lines") or [])


def _extract_word(line: str) -> str | None:
    pos_match = _POS_PATTERN.search(line)
    candidate_line = line[: pos_match.start()].strip() if pos_match else line
    match = _WORD_PATTERN.match(candidate_line)
    if not match:
        return None
    word = normalize_line(match.group(1)).strip(" -")
    return word if word and len(word.split()) <= 4 else None


def extract(unit: dict) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    source_pages = list(unit.get("source_pages") or [1])

    for raw_line in _candidate_lines(unit):
        line = normalize_line(raw_line)
        if not line or classify_section_heading(line) or parse_speaker_line(line):
            continue
        if not looks_like_vocabulary_entry(line):
            continue
        word = _extract_word(line)
        if not word:
            continue
        key = word.casefold()
        if key in seen:
            continue
        seen.add(key)
        pos_match = _POS_PATTERN.search(line)
        meaning_match = _CHINESE_PATTERN.search(line)
        items.append(
            {
                "word": word,
                "part_of_speech": f"{pos_match.group(1).lower()}." if pos_match else None,
                "meaning_zh": normalize_line(meaning_match.group(0)) if meaning_match else None,
                "source_pages": source_pages,
                "source_excerpt": line,
            }
        )
    return items
