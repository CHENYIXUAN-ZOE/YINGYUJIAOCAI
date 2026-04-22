from __future__ import annotations

import json

import pytest

from app.core.config import Settings
from app.services.parser import ocr_processor


def build_settings(tmp_path, credentials_path=None) -> Settings:
    settings = Settings(
        base_dir=tmp_path,
        data_dir=tmp_path / "data",
        temp_dir=tmp_path / "data" / "tmp",
        upload_dir=tmp_path / "data" / "uploads",
        parsed_dir=tmp_path / "data" / "parsed",
        export_dir=tmp_path / "data" / "exports",
        job_dir=tmp_path / "data" / "parsed" / "jobs",
        result_dir=tmp_path / "data" / "parsed" / "results",
        review_dir=tmp_path / "data" / "parsed" / "reviews",
        web_dir=tmp_path / "app" / "web",
        template_dir=tmp_path / "app" / "web" / "templates",
        static_dir=tmp_path / "app" / "web" / "static",
        google_application_credentials=str(credentials_path) if credentials_path else None,
        google_cloud_project=None,
    )
    settings.ensure_directories()
    return settings


def test_process_keeps_existing_text_when_ocr_api_is_not_configured(tmp_path, monkeypatch):
    settings = build_settings(tmp_path)
    monkeypatch.setattr(ocr_processor, "get_settings", lambda: settings)

    document = {
        "file_path": str(tmp_path / "sample.pdf"),
        "extractor": "pdftotext",
        "page_texts": ["Unit 1 Hello!\nLesson 1"],
    }

    result = ocr_processor.process(document)

    assert result["ocr_used"] is False
    assert result["ocr_backend"] == "pdftotext"
    assert result["page_count"] == 1
    assert result["page_lines"] == [
        {"page_num": 1, "line": "Unit 1 Hello!"},
        {"page_num": 1, "line": "Lesson 1"},
    ]


def test_process_rebuilds_document_from_gemini_ocr_output(tmp_path, monkeypatch):
    credentials_path = tmp_path / "creds.json"
    credentials_path.write_text(json.dumps({"project_id": "demo-project"}), encoding="utf-8")
    settings = build_settings(tmp_path, credentials_path=credentials_path)
    monkeypatch.setattr(ocr_processor, "get_settings", lambda: settings)
    monkeypatch.setattr(
        ocr_processor,
        "_extract_page_texts_with_gemini",
        lambda document, active_settings, progress_callback=None: [
            "Contents\nUnit 1 Hello! 2",
            "Unit 1 Hello!\nLesson 1 What's your name?",
        ],
    )

    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    document = {
        "file_path": str(pdf_path),
        "extractor": "pdftotext",
        "page_texts": ["stale text"],
        "page_lines": [{"page_num": 1, "line": "stale text"}],
        "lines": ["stale text"],
        "text": "stale text",
    }

    result = ocr_processor.process(document)

    assert result["ocr_used"] is True
    assert result["ocr_backend"] == "gemini_page_ocr"
    assert result["page_count"] == 2
    assert result["page_texts"][0] == "Contents\nUnit 1 Hello! 2"
    assert result["page_lines"] == [
        {"page_num": 1, "line": "Contents"},
        {"page_num": 1, "line": "Unit 1 Hello! 2"},
        {"page_num": 2, "line": "Unit 1 Hello!"},
        {"page_num": 2, "line": "Lesson 1 What's your name?"},
    ]
    assert result["text_layer_page_texts"] == ["stale text"]
    assert result["text_layer_page_lines"] == [{"page_num": 1, "line": "stale text"}]
    assert result["text_layer_lines"] == ["stale text"]


def test_normalize_ocr_payload_rejects_page_count_mismatch():
    with pytest.raises(ValueError):
        ocr_processor._normalize_ocr_payload(
            {"pages": [{"page_num": 1, "page_text": "hello"}]},
            [{"page_num": 1, "image_bytes": b"1"}, {"page_num": 2, "image_bytes": b"2"}],
        )
