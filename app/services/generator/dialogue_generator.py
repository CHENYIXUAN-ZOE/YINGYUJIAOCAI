from __future__ import annotations

from app.schemas.content import Classification, DialogueSample, DialogueTurn


def generate(classification: Classification, raw_dialogues: list[dict], unit_id: str) -> list[DialogueSample]:
    items: list[DialogueSample] = []
    for index, raw_dialogue in enumerate(raw_dialogues, start=1):
        turns = [
            DialogueTurn(
                turn_index=turn_index,
                speaker=turn["speaker"],
                text_en=turn["text_en"],
                text_zh=turn.get("text_zh", ""),
            )
            for turn_index, turn in enumerate(raw_dialogue.get("turns", []), start=1)
            if turn.get("speaker") and turn.get("text_en")
        ]
        if len(turns) < 2:
            continue
        items.append(
            DialogueSample(
                item_id=f"{unit_id}_dlg_{index}",
                classification=classification,
                title=raw_dialogue.get("title"),
                turns=turns,
                source_pages=list(raw_dialogue.get("source_pages") or [1]),
                source_excerpt=raw_dialogue.get("source_excerpt"),
            )
        )
    return items
