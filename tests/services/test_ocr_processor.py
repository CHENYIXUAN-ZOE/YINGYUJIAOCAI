from __future__ import annotations

import json
import sys
import types

import pytest

from app.core.errors import AppError
from app.core.config import Settings
from app.services.parser import ocr_processor


def build_settings(tmp_path, credentials_path=None, **overrides) -> Settings:
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
        **overrides,
    )
    settings.ensure_directories()
    return settings


def install_fake_google_modules(monkeypatch):
    google_module = types.ModuleType("google")
    genai_module = types.ModuleType("google.genai")
    errors_module = types.ModuleType("google.genai.errors")
    types_module = types.ModuleType("google.genai.types")
    oauth2_module = types.ModuleType("google.oauth2")
    service_account_module = types.ModuleType("google.oauth2.service_account")

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def close(self):
            return None

    class FakeHttpOptions:
        def __init__(self, api_version=None):
            self.api_version = api_version

    class FakeCredentials:
        @classmethod
        def from_service_account_file(cls, *args, **kwargs):
            return cls()

    genai_module.Client = FakeClient
    errors_module.APIError = RuntimeError
    types_module.HttpOptions = FakeHttpOptions
    service_account_module.Credentials = FakeCredentials

    google_module.genai = genai_module
    oauth2_module.service_account = service_account_module

    monkeypatch.setitem(sys.modules, "google", google_module)
    monkeypatch.setitem(sys.modules, "google.genai", genai_module)
    monkeypatch.setitem(sys.modules, "google.genai.errors", errors_module)
    monkeypatch.setitem(sys.modules, "google.genai.types", types_module)
    monkeypatch.setitem(sys.modules, "google.oauth2", oauth2_module)
    monkeypatch.setitem(sys.modules, "google.oauth2.service_account", service_account_module)


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


def test_process_prefers_embedded_text_layer_when_pdftotext_succeeds(tmp_path, monkeypatch):
    credentials_path = tmp_path / "creds.json"
    credentials_path.write_text(json.dumps({"project_id": "demo-project"}), encoding="utf-8")
    settings = build_settings(tmp_path, credentials_path=credentials_path)
    monkeypatch.setattr(ocr_processor, "get_settings", lambda: settings)

    def _unexpected_ocr_call(*args, **kwargs):
        raise AssertionError("OCR should not run when pdftotext already extracted text")

    monkeypatch.setattr(ocr_processor, "_extract_page_texts_with_gemini", _unexpected_ocr_call)

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


def test_process_uses_ocr_when_embedded_text_layer_is_low_quality(tmp_path, monkeypatch):
    credentials_path = tmp_path / "creds.json"
    credentials_path.write_text(json.dumps({"project_id": "demo-project"}), encoding="utf-8")
    settings = build_settings(tmp_path, credentials_path=credentials_path)
    monkeypatch.setattr(ocr_processor, "get_settings", lambda: settings)
    monkeypatch.setattr(
        ocr_processor,
        "_extract_page_texts_with_gemini",
        lambda document, active_settings, progress_callback=None: [
            "Unit 1 Signs\nLesson 1\nDon't walk.",
        ],
    )

    document = {
        "file_path": str(tmp_path / "sample.pdf"),
        "extractor": "pdftotext",
        "page_texts": ["@@@ ### ===\n12345\n:::\n" * 20],
    }

    result = ocr_processor.process(document)

    assert result["ocr_used"] is True
    assert result["ocr_backend"] == "gemini_page_ocr"
    assert result["page_count"] == 1
    assert result["page_lines"] == [
        {"page_num": 1, "line": "Unit 1 Signs"},
        {"page_num": 1, "line": "Lesson 1"},
        {"page_num": 1, "line": "Don't walk."},
    ]
    assert result["text_layer_page_texts"] == ["@@@ ### ===\n12345\n:::\n" * 20]


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
        "extractor": "raw_stream",
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


def test_extract_page_texts_reuses_cached_batches_on_second_run(tmp_path, monkeypatch):
    credentials_path = tmp_path / "creds.json"
    credentials_path.write_text(json.dumps({"project_id": "demo-project"}), encoding="utf-8")
    settings = build_settings(tmp_path, credentials_path=credentials_path, ocr_page_batch_size=2)
    install_fake_google_modules(monkeypatch)

    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(ocr_processor, "_resolve_page_count", lambda _document: 4)

    render_calls: list[tuple[int, int]] = []
    monkeypatch.setattr(
        ocr_processor,
        "_render_page_images",
        lambda _file_path, _settings, page_start, page_end, _render_dpi: render_calls.append((page_start, page_end))
        or [{"page_num": page_num, "image_bytes": f"page-{page_num}".encode("utf-8")} for page_num in range(page_start, page_end + 1)],
    )

    ocr_calls: list[list[int]] = []

    def fake_ocr_batch(_client, _types, _genai_errors, _settings, rendered_pages, _max_attempts):
        page_nums = [page["page_num"] for page in rendered_pages]
        ocr_calls.append(page_nums)
        return [f"Page {page_num}" for page_num in page_nums]

    monkeypatch.setattr(ocr_processor, "_ocr_page_batch", fake_ocr_batch)

    document = {"file_path": str(pdf_path)}

    first_result = ocr_processor._extract_page_texts_with_gemini(document, settings)
    second_result = ocr_processor._extract_page_texts_with_gemini(document, settings)

    assert first_result == ["Page 1", "Page 2", "Page 3", "Page 4"]
    assert second_result == first_result
    assert ocr_calls == [[1, 2], [3, 4]]
    assert render_calls == [(1, 2), (3, 4)]


def test_extract_page_texts_reuses_completed_batches_after_failure(tmp_path, monkeypatch):
    credentials_path = tmp_path / "creds.json"
    credentials_path.write_text(json.dumps({"project_id": "demo-project"}), encoding="utf-8")
    settings = build_settings(
        tmp_path,
        credentials_path=credentials_path,
        ocr_page_batch_size=2,
        gemini_max_retries=1,
    )
    install_fake_google_modules(monkeypatch)

    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(ocr_processor, "_resolve_page_count", lambda _document: 6)

    render_calls: list[tuple[int, int]] = []
    monkeypatch.setattr(
        ocr_processor,
        "_render_page_images",
        lambda _file_path, _settings, page_start, page_end, _render_dpi: render_calls.append((page_start, page_end))
        or [{"page_num": page_num, "image_bytes": f"page-{page_num}".encode("utf-8")} for page_num in range(page_start, page_end + 1)],
    )

    first_run_calls: list[list[int]] = []

    def fail_on_second_batch(_client, _types, _genai_errors, _settings, rendered_pages, _max_attempts):
        page_nums = [page["page_num"] for page in rendered_pages]
        first_run_calls.append(page_nums)
        if page_nums == [3, 4]:
            raise AppError("OCR_REQUEST_FAILED", "boom", status_code=502)
        return [f"Page {page_num}" for page_num in page_nums]

    monkeypatch.setattr(ocr_processor, "_ocr_page_batch", fail_on_second_batch)

    with pytest.raises(AppError):
        ocr_processor._extract_page_texts_with_gemini({"file_path": str(pdf_path)}, settings)

    second_run_calls: list[list[int]] = []

    def succeed_remaining_batches(_client, _types, _genai_errors, _settings, rendered_pages, _max_attempts):
        page_nums = [page["page_num"] for page in rendered_pages]
        second_run_calls.append(page_nums)
        return [f"Page {page_num}" for page_num in page_nums]

    monkeypatch.setattr(ocr_processor, "_ocr_page_batch", succeed_remaining_batches)
    render_calls.clear()

    result = ocr_processor._extract_page_texts_with_gemini({"file_path": str(pdf_path)}, settings)

    assert first_run_calls == [[1, 2], [3, 4]]
    assert second_run_calls == [[3, 4], [5, 6]]
    assert render_calls == [(3, 4), (5, 6)]
    assert result == ["Page 1", "Page 2", "Page 3", "Page 4", "Page 5", "Page 6"]
