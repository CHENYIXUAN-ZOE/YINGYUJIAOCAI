from __future__ import annotations

from app.services.parser.unit_detector import detect


def test_detect_prefers_front_toc_cluster_over_word_list_like_pages():
    document = {
        "stem": "sample",
        "page_lines": [
            {"page_num": 3, "line": "Unit 1 Hello! 2"},
            {"page_num": 3, "line": "Unit 2 Friends 14"},
            {"page_num": 3, "line": "Unit 3 Playing Together 26"},
            {"page_num": 3, "line": "Unit 4 My Family 38"},
            {"page_num": 3, "line": "Un i t 5 My Things 50"},
            {"page_num": 3, "line": "Un i t 6 Review 62"},
            {"page_num": 3, "line": "Progress Check 73"},
            {"page_num": 4, "line": "Lesson 1"},
            {"page_num": 16, "line": "This is Danny Deer."},
            {"page_num": 28, "line": "Let's play football!"},
            {"page_num": 40, "line": "This is my family."},
            {"page_num": 52, "line": "Whose bag is this?"},
            {"page_num": 64, "line": "Review"},
            {"page_num": 80, "line": "Unit 1 tiger 16"},
            {"page_num": 80, "line": "Unit 3 OK 26"},
            {"page_num": 81, "line": "Unit 4 bike 52"},
            {"page_num": 81, "line": "Unit 5 ball 60"},
        ],
    }

    units = detect(document)

    assert len(units) == 6
    assert units[0]["unit_code"] == "Unit 1"
    assert units[0]["unit_name"] == "Hello!"
    assert units[0]["source_pages"][0] == 4
    assert units[1]["unit_name"] == "Friends"
    assert units[2]["unit_name"] == "Playing Together"
    assert units[4]["unit_name"] == "My Things"
    assert units[5]["unit_code"] == "Unit 6"
    assert units[5]["source_pages"][0] == 64


def test_detect_uses_filtered_page_lines_for_body_headers():
    document = {
        "stem": "sample",
        "page_count": 6,
        "page_lines": [
            {"page_num": 1, "line": "English Book 3A"},
            {"page_num": 2, "line": "English Book 3A"},
            {"page_num": 3, "line": "English Book 3A"},
        ],
        "content_page_lines": [
            {"page_num": 2, "line": "Unit 1 My Family"},
            {"page_num": 2, "line": "Lesson 1"},
            {"page_num": 3, "line": "Who is he?"},
            {"page_num": 4, "line": "Unit 2 My School"},
            {"page_num": 4, "line": "Lesson 1"},
            {"page_num": 5, "line": "This is my school."},
        ],
    }

    units = detect(document)

    assert len(units) == 2
    assert units[0]["unit_code"] == "Unit 1"
    assert units[0]["source_pages"] == [2, 3]
    assert units[1]["unit_code"] == "Unit 2"
    assert units[1]["source_pages"] == [4, 5]
