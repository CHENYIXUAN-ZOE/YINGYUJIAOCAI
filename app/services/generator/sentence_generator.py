from __future__ import annotations

from app.schemas.content import Classification, SentencePattern


def generate(classification: Classification, raw_items: list[dict], unit_id: str) -> list[SentencePattern]:
    items: list[SentencePattern] = []
    for index, raw in enumerate(raw_items, start=1):
        examples = {
            "Who's this?": ["Who's this? 这是谁？", "Who's this in the photo? 这张照片里是谁？"],
            "This is my ...": ["This is my father. 这是我的爸爸。", "This is my sister. 这是我的妹妹。"],
            "Is he your ...?": ["Is he your brother? 他是你的哥哥吗？", "Is he your father? 他是你的爸爸吗？"],
        }.get(raw["pattern"], [raw["pattern"]])
        items.append(
            SentencePattern(
                item_id=f"{unit_id}_sp_{index}",
                classification=classification,
                pattern=raw["pattern"],
                usage_note=raw.get("usage_note"),
                examples=examples[:2],
                source_pages=[1],
                source_excerpt=raw["pattern"],
            )
        )
    return items
