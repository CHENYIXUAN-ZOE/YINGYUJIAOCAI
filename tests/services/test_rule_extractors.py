from __future__ import annotations

from app.services.parser import dialogue_extractor, sentence_extractor, vocabulary_extractor


def test_vocabulary_extractor_uses_real_section_lines():
    unit = {
        "source_pages": [4, 5],
        "section_lines": {
            "vocabulary": [
                "Words",
                "school n. 学校",
                "classroom n. 教室",
                "library 图书馆",
            ]
        },
    }

    items = vocabulary_extractor.extract(unit)

    assert [item["word"] for item in items] == ["school", "classroom", "library"]
    assert items[0]["meaning_zh"] == "学校"
    assert items[0]["source_pages"] == [4, 5]


def test_sentence_extractor_uses_real_section_lines():
    unit = {
        "source_pages": [6],
        "section_lines": {
            "sentence_patterns": [
                "Key Sentences",
                "Where is the library? 图书馆在哪里？",
                "This is our classroom.",
            ]
        },
    }

    items = sentence_extractor.extract(unit)

    assert [item["pattern"] for item in items] == ["Where is the library?", "This is our classroom."]
    assert items[0]["usage_note"]
    assert items[0]["source_pages"] == [6]


def test_dialogue_extractor_uses_real_speaker_lines():
    unit = {
        "unit_code": "Unit 2",
        "unit_name": "My School",
        "unit_theme": "My School",
        "source_pages": [7, 8],
        "section_lines": {
            "dialogue_samples": [
                "Listen and say",
                "A: Where is the library?",
                "B: It is next to the classroom.",
                "A: Thank you.",
                "B: You are welcome.",
            ]
        },
    }

    dialogues = dialogue_extractor.extract(unit)

    assert len(dialogues) == 1
    assert dialogues[0]["title"] == "My School"
    assert [turn["speaker"] for turn in dialogues[0]["turns"]] == ["A", "B", "A", "B"]
    assert dialogues[0]["source_pages"] == [7, 8]
