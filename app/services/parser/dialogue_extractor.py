from __future__ import annotations


def extract(unit: dict) -> dict:
    return {
        "title": f"{unit['unit_code']} Dialogue",
        "speakers": ["A", "B"],
        "theme": unit.get("unit_theme", "教材主题"),
    }
