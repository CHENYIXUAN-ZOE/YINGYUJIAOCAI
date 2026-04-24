from __future__ import annotations

from app.services.parser.heuristics import classify_section_heading, normalize_line, parse_speaker_line


def _candidate_lines(unit: dict) -> list[str]:
    section_lines = unit.get("section_lines") or {}
    return list(section_lines.get("dialogue_samples") or unit.get("lines") or [])


def _finalize_dialogue(unit: dict, turns: list[dict], source_pages: list[int]) -> dict:
    excerpt = " ".join(turn["text_en"] for turn in turns[:4]).strip()
    return {
        "title": unit.get("unit_theme") or unit.get("unit_name") or f"{unit['unit_code']} Dialogue",
        "turns": turns,
        "source_pages": source_pages,
        "source_excerpt": excerpt,
    }


def extract(unit: dict) -> list[dict]:
    dialogues: list[dict] = []
    current_turns: list[dict] = []
    source_pages = list(unit.get("source_pages") or [1])

    for raw_line in _candidate_lines(unit):
        line = normalize_line(raw_line)
        if not line:
            continue
        if classify_section_heading(line):
            if len(current_turns) >= 2:
                dialogues.append(_finalize_dialogue(unit, current_turns, source_pages))
            current_turns = []
            continue
        parsed = parse_speaker_line(line)
        if parsed:
            speaker, text_en = parsed
            current_turns.append({"speaker": speaker, "text_en": text_en, "text_zh": ""})
            continue
        if len(current_turns) >= 2:
            dialogues.append(_finalize_dialogue(unit, current_turns, source_pages))
        current_turns = []

    if len(current_turns) >= 2:
        dialogues.append(_finalize_dialogue(unit, current_turns, source_pages))

    return dialogues
