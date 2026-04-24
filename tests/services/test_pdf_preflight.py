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


def test_analyze_pdf_marks_weak_text_layer_as_mixed(tmp_path, monkeypatch):
    pdf_path = tmp_path / "weak-text.pdf"
    pdf_path.write_bytes(b"x" * (12 * 1024 * 1024))

    monkeypatch.setattr(pdf_preflight, "_read_page_count", lambda _: 40)
    monkeypatch.setattr(
        pdf_preflight,
        "_extract_text_sample",
        lambda *_args, **_kwargs: ("@@@ ### ===\n12345\n:::\n" * 20),
    )

    result = pdf_preflight.analyze_pdf(pdf_path)

    assert result.detected_pdf_type == "mixed"
    assert result.text_layer_detected is False
    assert any("文字层较弱" in warning for warning in result.warnings)


def test_analyze_pdf_keeps_noisy_but_readable_toc_as_text(tmp_path, monkeypatch):
    pdf_path = tmp_path / "noisy-text.pdf"
    pdf_path.write_bytes(b"x" * (18 * 1024 * 1024))

    monkeypatch.setattr(pdf_preflight, "_read_page_count", lambda _: 84)
    monkeypatch.setattr(
        pdf_preflight,
        "_extract_text_sample",
        lambda *_args, **_kwargs: (
            "夸oe@e\n三年级上册\n"
            ",!111111111111111111111111111111111111111111111111 匕\n"
            "兰\n三巨\n"
            "Unit 1 Hello! 2\n"
            "Unit 2 Friends 14\n"
            "Unit 3 Playing Together 26\n"
            "Unit 4 My Family 38\n"
            "Unit 5 My Things 50\n"
            "Unit 6 Review 62\n"
            "Progress Check 73\n"
            "Word List 80\n"
        ),
    )

    result = pdf_preflight.analyze_pdf(pdf_path)

    assert result.detected_pdf_type == "text"
    assert result.text_layer_detected is True
