from __future__ import annotations

from app.schemas.content import Classification, VocabularyItem


def generate(classification: Classification, raw_items: list[dict], unit_id: str) -> list[VocabularyItem]:
    items: list[VocabularyItem] = []
    for index, raw in enumerate(raw_items, start=1):
        items.append(
            VocabularyItem(
                item_id=f"{unit_id}_voc_{index}",
                classification=classification,
                word=raw["word"],
                part_of_speech=raw.get("part_of_speech"),
                meaning_zh=raw.get("meaning_zh"),
                example_sentences=[sentence for sentence in raw.get("example_sentences", []) if sentence][:2],
                source_pages=list(raw.get("source_pages") or [1]),
                source_excerpt=raw.get("source_excerpt") or raw["word"],
            )
        )
    return items
