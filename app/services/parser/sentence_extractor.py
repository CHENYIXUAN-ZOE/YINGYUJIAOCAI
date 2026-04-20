from __future__ import annotations


def extract(unit: dict) -> list[dict]:
    return [
        {"pattern": "Who's this?", "usage_note": "询问人物身份"},
        {"pattern": "This is my ...", "usage_note": "介绍家庭成员"},
        {"pattern": "Is he your ...?", "usage_note": "确认人物关系"},
    ]
