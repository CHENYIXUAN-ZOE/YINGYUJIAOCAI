from __future__ import annotations

from app.schemas.content import Classification, SentencePattern


def generate(classification: Classification, raw_items: list[dict], unit_id: str) -> list[SentencePattern]:
    items: list[SentencePattern] = []
    for index, raw in enumerate(raw_items, start=1):
        items.append(
            SentencePattern(
                item_id=f"{unit_id}_sp_{index}",
                classification=classification,
                pattern=raw["pattern"],
                usage_note=raw.get("usage_note"),
                examples=[example for example in raw.get("examples", []) if example][:2],
                source_pages=list(raw.get("source_pages") or [1]),
                source_excerpt=raw.get("source_excerpt") or raw["pattern"],
            )
        )
    return items
