from __future__ import annotations


def detect(document: dict) -> list[dict]:
    stem = document.get("stem", "教材")
    return [
        {
            "unit_code": "Unit 1",
            "unit_name": f"{stem[:18]} 单元" if stem else "Auto Parsed Unit",
            "unit_theme": "教材单元主题",
            "source_pages": [1],
        }
    ]
