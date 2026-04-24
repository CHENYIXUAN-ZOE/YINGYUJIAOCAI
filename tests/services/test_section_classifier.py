from __future__ import annotations

from app.services.parser.section_classifier import assess_classification, classify


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


def test_assess_classification_marks_missing_sections_low_confidence():
    units = [
        {
            "unit_code": "Unit 1",
            "unit_name": "Unit 1",
            "lines": [
                "This page has many lines but no usable structure.",
                "The cat is on the chair.",
                "We can play in the park.",
                "They are happy today.",
                "This sentence keeps going.",
                "Another plain sentence here.",
                "One more plain line.",
                "Last plain line.",
            ],
        },
        {
            "unit_code": "Unit 2",
            "unit_name": "Unit 2",
            "lines": [
                "This unit also lacks headings and patterns.",
                "Children read books after school.",
                "The playground is big and clean.",
                "Everyone likes sunny days.",
                "They walk home together.",
                "Music is fun in class.",
                "Lunch is ready at noon.",
                "We finish work early.",
            ],
        },
    ]

    classified_units = classify({"page_count": 28}, units)
    assessment = assess_classification({"page_count": 28}, classified_units)

    assert assessment["low_confidence"] is True
    assert "most_substantial_units_lack_section_signals" in assessment["low_confidence_reasons"]
