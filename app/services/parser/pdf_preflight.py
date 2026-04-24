from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from app.core.config import get_settings
from app.schemas.job import PdfPreflight

_PAGE_COUNT_PATTERN = re.compile(r"^Pages:\s+(\d+)$", re.MULTILINE)
_TEXT_SAMPLE_THRESHOLD = 80


def analyze_pdf(file_path: Path) -> PdfPreflight:
    settings = get_settings()
    file_size_mb = round(file_path.stat().st_size / 1024 / 1024, 2) if file_path.exists() else 0
    page_count = _read_page_count(file_path)
    text_sample = _extract_text_sample(file_path, max_pages=settings.preflight_sample_pages)
    text_sample_chars = len(text_sample.strip())
    detected_pdf_type = _classify_pdf_type(text_sample_chars)
    eta_min_sec, eta_max_sec = _estimate_duration_window(page_count, detected_pdf_type)
    estimated_duration_sec = int((eta_min_sec + eta_max_sec) / 2) if eta_max_sec else 0
    within_duration_budget = eta_max_sec <= settings.target_parse_duration_sec if eta_max_sec else False
    warnings = _build_warnings(
        page_count=page_count,
        detected_pdf_type=detected_pdf_type,
        eta_max_sec=eta_max_sec,
        duration_budget_sec=settings.target_parse_duration_sec,
        file_size_mb=file_size_mb,
    )

    return PdfPreflight(
        file_size_mb=file_size_mb,
        page_count=page_count,
        text_layer_detected=text_sample_chars >= _TEXT_SAMPLE_THRESHOLD,
        detected_pdf_type=detected_pdf_type,
        estimated_duration_sec=estimated_duration_sec,
        estimated_duration_range=_format_duration_window(eta_min_sec, eta_max_sec),
        duration_budget_sec=settings.target_parse_duration_sec,
        within_duration_budget=within_duration_budget,
        warnings=warnings,
    )


def _read_page_count(file_path: Path) -> int:
    if not shutil.which("pdfinfo") or not file_path.exists():
        return 0
    try:
        completed = subprocess.run(
            ["pdfinfo", str(file_path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return 0
    match = _PAGE_COUNT_PATTERN.search(completed.stdout)
    return int(match.group(1)) if match else 0


def _extract_text_sample(file_path: Path, *, max_pages: int) -> str:
    if not shutil.which("pdftotext") or not file_path.exists():
        return ""
    try:
        completed = subprocess.run(
            ["pdftotext", "-f", "1", "-l", str(max_pages), "-layout", str(file_path), "-"],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return completed.stdout.decode("utf-8", "ignore")


def _classify_pdf_type(text_sample_chars: int) -> str:
    if text_sample_chars >= _TEXT_SAMPLE_THRESHOLD:
        return "text"
    if text_sample_chars > 0:
        return "mixed"
    return "scan"


def _estimate_duration_window(page_count: int, detected_pdf_type: str) -> tuple[int, int]:
    effective_pages = max(1, page_count)
    if detected_pdf_type == "text":
        return 90 + effective_pages * 3, 180 + effective_pages * 5
    if detected_pdf_type == "mixed":
        return 150 + effective_pages * 4, 240 + effective_pages * 6
    return 240 + effective_pages * 6, 360 + effective_pages * 9


def _format_duration_window(eta_min_sec: int, eta_max_sec: int) -> str:
    return f"{_format_minutes(eta_min_sec)} - {_format_minutes(eta_max_sec)}"


def _format_minutes(seconds: int) -> str:
    minutes = max(1, round(seconds / 60))
    return f"{minutes} 分钟"


def _build_warnings(
    *,
    page_count: int,
    detected_pdf_type: str,
    eta_max_sec: int,
    duration_budget_sec: int,
    file_size_mb: float,
) -> list[str]:
    warnings: list[str] = []
    if page_count >= 80:
        warnings.append("教材页数较多，整本处理时间会明显增加。")
    if detected_pdf_type == "scan":
        warnings.append("检测为扫描版或低文字层 PDF，处理时会走 OCR，整体速度更慢。")
    elif detected_pdf_type == "mixed":
        warnings.append("检测到文字层较弱，部分页面可能仍需 OCR。")
    if eta_max_sec > duration_budget_sec:
        warnings.append(f"预计处理时间可能超过 {round(duration_budget_sec / 60)} 分钟。")
    if file_size_mb >= 80:
        warnings.append("文件体积较大，上传和预处理时间会增加。")
    return warnings
