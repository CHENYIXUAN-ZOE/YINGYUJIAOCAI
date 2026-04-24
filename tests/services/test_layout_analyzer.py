from __future__ import annotations

from app.services.parser.layout_analyzer import analyze


def test_analyze_filters_repeated_header_footer_lines():
    document = {
        "page_lines": [
            {"page_num": 1, "line": "English Book 3A"},
            {"page_num": 1, "line": "Unit 1 My Family"},
            {"page_num": 1, "line": "3"},
            {"page_num": 2, "line": "English Book 3A"},
            {"page_num": 2, "line": "Who is he?"},
            {"page_num": 2, "line": "4"},
            {"page_num": 3, "line": "English Book 3A"},
            {"page_num": 3, "line": "This is my family."},
            {"page_num": 3, "line": "5"},
        ]
    }

    analyzed = analyze(document)

    assert analyzed["page_count"] == 3
    assert "English Book 3A" in analyzed["layout"]["repeated_lines"]
    filtered_lines = analyzed["content_page_lines"]
    assert {"page_num": 1, "line": "English Book 3A"} not in filtered_lines
    assert {"page_num": 2, "line": "Who is he?"} in filtered_lines
