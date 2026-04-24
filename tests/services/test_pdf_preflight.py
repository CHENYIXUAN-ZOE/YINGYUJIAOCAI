from __future__ import annotations

from app.services.parser import pdf_preflight


def test_analyze_pdf_detects_text_pdf_within_budget(tmp_path, monkeypatch):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"x" * (4 * 1024 * 1024))

    monkeypatch.setattr(pdf_preflight, "_read_page_count", lambda _: 48)
    monkeypatch.setattr(
        pdf_preflight,
        "_extract_text_sample",
        lambda *_args, **_kwargs: "Unit 1 Hello!\nLesson 1\n" * 20,
    )

    result = pdf_preflight.analyze_pdf(pdf_path)

    assert result.detected_pdf_type == "text"
    assert result.text_layer_detected is True
    assert result.page_count == 48
    assert result.within_duration_budget is True
    assert result.estimated_duration_range is not None


def test_analyze_pdf_marks_scan_pdf_as_over_budget(tmp_path, monkeypatch):
    pdf_path = tmp_path / "scan.pdf"
    pdf_path.write_bytes(b"x" * (90 * 1024 * 1024))

    monkeypatch.setattr(pdf_preflight, "_read_page_count", lambda _: 96)
    monkeypatch.setattr(pdf_preflight, "_extract_text_sample", lambda *_args, **_kwargs: "")

    result = pdf_preflight.analyze_pdf(pdf_path)

    assert result.detected_pdf_type == "scan"
    assert result.text_layer_detected is False
    assert result.within_duration_budget is False
    assert any("扫描版" in warning for warning in result.warnings)
    assert any("10 分钟" in warning for warning in result.warnings)
