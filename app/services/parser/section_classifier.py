from __future__ import annotations


def classify(document: dict, units: list[dict]) -> list[dict]:
    for unit in units:
        unit["sections"] = ["vocabulary", "sentence_patterns", "dialogue_samples"]
    return units
