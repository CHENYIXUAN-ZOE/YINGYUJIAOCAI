from __future__ import annotations

from app.services.parser.section_classifier import classify


def test_classify_derives_sections_from_headings_and_line_patterns():
    units = [
        {
            "unit_code": "Unit 1",
            "unit_name": "My Family",
            "lines": [
                "Words",
                "family n.",
                "father n.",
                "Key Sentences",
                "Who is he?",
                "This is my father.",
                "Listen and say",
                "A: Who is he?",
                "B: He is my father.",
            ],
        }
    ]

    classified_units = classify({}, units)
    unit = classified_units[0]

    assert unit["sections"] == ["vocabulary", "sentence_patterns", "dialogue_samples"]
    assert unit["section_lines"]["vocabulary"] == ["family n.", "father n."]
    assert "Who is he?" in unit["section_lines"]["sentence_patterns"]
    assert "A: Who is he?" in unit["section_lines"]["dialogue_samples"]
