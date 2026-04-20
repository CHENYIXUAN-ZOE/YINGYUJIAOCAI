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
                example_sentences=[
                    f"This is my {raw['word']}.",
                    f"I can talk about {raw['word']} in this unit.",
                ][:2],
                source_pages=[1],
                source_excerpt=raw["word"],
            )
        )
    return items
