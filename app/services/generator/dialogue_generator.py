from __future__ import annotations

from app.schemas.content import Classification, DialogueSample, DialogueTurn


def generate(classification: Classification, raw_dialogue: dict, unit_id: str) -> list[DialogueSample]:
    lines = [
        ("A", "Hello! Who's this in your photo?", "你好！你照片里这是谁？"),
        ("B", "This is my father.", "这是我的爸爸。"),
        ("A", "Is he your father or your uncle?", "他是你的爸爸还是你的叔叔？"),
        ("B", "He is my father.", "他是我的爸爸。"),
        ("A", "Who is that woman?", "那个女人是谁？"),
        ("B", "That is my mother.", "那是我的妈妈。"),
        ("A", "Do you have a brother?", "你有哥哥或弟弟吗？"),
        ("B", "Yes, I have a brother.", "有，我有一个哥哥。"),
        ("A", "Who's this boy?", "这个男孩是谁？"),
        ("B", "This is my brother.", "这是我的哥哥。"),
    ]
    turns = [
        DialogueTurn(turn_index=index, speaker=speaker, text_en=text_en, text_zh=text_zh)
        for index, (speaker, text_en, text_zh) in enumerate(lines, start=1)
    ]
    return [
        DialogueSample(
            item_id=f"{unit_id}_dlg_1",
            classification=classification,
            title=raw_dialogue.get("title"),
            turns=turns,
            source_pages=[1],
            source_excerpt="Sample dialogue generated from placeholder parser output.",
        )
    ]
