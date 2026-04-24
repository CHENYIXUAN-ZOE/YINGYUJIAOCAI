from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.services.parser.heuristics import normalize_line
from app.services.parser.pdf_preflight import assess_text_sample

_RENDERED_PAGE_PATTERN = re.compile(r"page-(\d+)\.png$")
_PAGE_COUNT_PATTERN = re.compile(r"^Pages:\s+(\d+)\s*$", re.MULTILINE)
_OCR_CACHE_VERSION = "v1"
_OCR_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "pages": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "page_num": {"type": "INTEGER"},
                    "page_text": {"type": "STRING"},
                },
                "required": ["page_num", "page_text"],
            },
        }
    },
    "required": ["pages"],
}
_OCR_INSTRUCTIONS = (
    "Transcribe each textbook page image into plain text. "
    "Preserve reading order and preserve visible line breaks. "
    "Use newline characters between distinct printed lines or list entries. "
    "Keep printed page numbers if they are visible. "
    "Do not summarize, translate, normalize spelling, or invent missing text. "
    "Return JSON with key pages, an array of objects with page_num and page_text, "
    "in the same order as the images."
)


def process(document: dict, progress_callback=None) -> dict:
    settings = get_settings()
    _rebuild_document_text(document, document.get("page_texts") or [])

    if _should_use_embedded_text(document, settings):
        document["ocr_used"] = False
        document["ocr_backend"] = document.get("extractor") or "pdf_text"
        document["page_count"] = _resolve_page_count(document)
        return document

    if not _ocr_api_ready(settings):
        document["ocr_used"] = False
        document["ocr_backend"] = document.get("extractor") or "pdf_text"
        document["page_count"] = _resolve_page_count(document)
        return document

    original_page_texts = list(document.get("page_texts") or [])
    original_page_lines = list(document.get("page_lines") or [])
    original_lines = list(document.get("lines") or [])

    ocr_page_texts = _extract_page_texts_with_gemini(document, settings, progress_callback=progress_callback)
    if not any(text.strip() for text in ocr_page_texts):
        raise AppError(
            "OCR_EMPTY_RESULT",
            "OCR API returned no readable text",
            status_code=502,
            details={"backend": "gemini_page_ocr"},
        )

    _rebuild_document_text(document, ocr_page_texts)
    document["ocr_used"] = True
    document["ocr_backend"] = "gemini_page_ocr"
    document["page_count"] = len(ocr_page_texts)
    document["text_layer_page_texts"] = original_page_texts
    document["text_layer_page_lines"] = original_page_lines
    document["text_layer_lines"] = original_lines
    return document


def _rebuild_document_text(document: dict, page_texts: list[str]) -> dict:
    normalized_page_texts = [str(page_text or "") for page_text in page_texts]
    page_lines: list[dict] = []
    lines: list[str] = []
    for page_num, page_text in enumerate(normalized_page_texts, start=1):
        normalized_lines = [normalize_line(line) for line in page_text.splitlines() if normalize_line(line)]
        for line in normalized_lines:
            page_lines.append({"page_num": page_num, "line": line})
        lines.extend(normalized_lines)

    document["page_texts"] = normalized_page_texts
    document["page_lines"] = page_lines
    document["lines"] = lines
    document["text"] = "\n".join(normalized_page_texts)
    return document


def _should_use_embedded_text(document: dict, settings: Settings) -> bool:
    if document.get("extractor") != "pdftotext":
        return False
    page_texts = [str(page_text or "") for page_text in document.get("page_texts") or []]
    if not any(page_text.strip() for page_text in page_texts):
        return False
    sample_text = "\n".join(page_texts[: max(1, min(settings.preflight_sample_pages, len(page_texts)))])
    return assess_text_sample(sample_text).usable_text_layer


def _ocr_api_ready(settings: Settings) -> bool:
    credentials_path = settings.resolve_google_credentials_path()
    return bool(credentials_path and credentials_path.exists())


def _resolve_project_id(settings: Settings, credentials_path: Path | None) -> str | None:
    if settings.google_cloud_project:
        return settings.google_cloud_project
    if not credentials_path or not credentials_path.exists():
        return None
    try:
        payload = json.loads(credentials_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    project_id = payload.get("project_id")
    return str(project_id) if project_id else None


def _resolve_page_count(document: dict) -> int:
    page_texts = document.get("page_texts") or []
    if page_texts:
        return len(page_texts)

    page_lines = document.get("page_lines") or []
    if page_lines:
        return max(int(item.get("page_num", 1)) for item in page_lines)

    file_path = document.get("file_path")
    if file_path:
        probed_count = _probe_page_count(Path(file_path))
        if probed_count:
            return probed_count
    return 1


def _probe_page_count(file_path: Path) -> int | None:
    if not shutil.which("pdfinfo"):
        return None
    try:
        completed = subprocess.run(
            ["pdfinfo", str(file_path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None

    match = _PAGE_COUNT_PATTERN.search(completed.stdout)
    if not match:
        return None
    return int(match.group(1))


def _extract_page_texts_with_gemini(document: dict, settings: Settings, progress_callback=None) -> list[str]:
    file_path = Path(document.get("file_path", ""))
    if not file_path.exists():
        raise AppError("PDF_NOT_FOUND", "source PDF is missing", status_code=404)
    if not shutil.which("pdftoppm"):
        raise AppError(
            "PDF_RENDERER_MISSING",
            "pdftoppm is required for OCR image rendering",
            status_code=500,
        )

    credentials_path = settings.resolve_google_credentials_path()
    project_id = _resolve_project_id(settings, credentials_path)
    if not credentials_path or not credentials_path.exists() or not project_id:
        raise AppError(
            "OCR_CONFIG_INVALID",
            "OCR API credentials or project configuration is invalid",
            status_code=500,
        )

    try:
        from google import genai
        from google.genai import errors as genai_errors
        from google.genai import types
        from google.oauth2 import service_account
    except ImportError as exc:
        raise AppError(
            "GEMINI_SDK_MISSING",
            "google-genai dependency is missing; install requirements before using OCR API",
            status_code=500,
            details={"missing_module": str(exc)},
        ) from exc

    page_count = _resolve_page_count(document)
    batch_size = max(1, min(settings.ocr_page_batch_size, 4))
    render_dpi = max(120, min(settings.ocr_render_dpi, 240))
    max_attempts = max(1, settings.gemini_max_retries)
    cache_namespace = _build_ocr_cache_namespace(file_path, settings, render_dpi)
    credentials = service_account.Credentials.from_service_account_file(
        str(credentials_path),
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )

    client = genai.Client(
        vertexai=True,
        project=project_id,
        location=settings.google_cloud_location,
        credentials=credentials,
        http_options=types.HttpOptions(api_version="v1"),
    )
    page_texts: list[str] = []
    try:
        for page_start in range(1, page_count + 1, batch_size):
            page_end = min(page_start + batch_size - 1, page_count)
            cached_batch = _load_cached_ocr_batch(settings, cache_namespace, page_start, page_end)
            if cached_batch is None:
                rendered_pages = _render_page_images(file_path, settings, page_start, page_end, render_dpi)
                cached_batch = _ocr_page_batch(client, types, genai_errors, settings, rendered_pages, max_attempts)
                _save_cached_ocr_batch(settings, cache_namespace, page_start, page_end, cached_batch)
            page_texts.extend(cached_batch)
            if progress_callback:
                progress_callback(page_end, page_count)
    finally:
        client.close()

    return page_texts


def _render_page_images(
    file_path: Path,
    settings: Settings,
    page_start: int,
    page_end: int,
    render_dpi: int,
) -> list[dict]:
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(dir=settings.temp_dir) as tmpdir:
            batch_dir = Path(tmpdir)
            prefix = batch_dir / "page"
            subprocess.run(
                [
                    "pdftoppm",
                    "-png",
                    "-f",
                    str(page_start),
                    "-l",
                    str(page_end),
                    "-r",
                    str(render_dpi),
                    str(file_path),
                    str(prefix),
                ],
                check=True,
                capture_output=True,
            )

            rendered_by_page: dict[int, bytes] = {}
            for image_path in batch_dir.glob("page-*.png"):
                match = _RENDERED_PAGE_PATTERN.search(image_path.name)
                if not match:
                    continue
                rendered_by_page[int(match.group(1))] = image_path.read_bytes()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise AppError(
            "PDF_RENDER_FAILED",
            "failed to render PDF pages for OCR",
            status_code=500,
            details={"page_start": page_start, "page_end": page_end, "message": str(exc)},
        ) from exc

    rendered_pages: list[dict] = []
    for page_num in range(page_start, page_end + 1):
        image_bytes = rendered_by_page.get(page_num)
        if not image_bytes:
            raise AppError(
                "PDF_RENDER_FAILED",
                "rendered PDF page image is missing",
                status_code=500,
                details={"page_num": page_num},
            )
        rendered_pages.append({"page_num": page_num, "image_bytes": image_bytes})
    return rendered_pages


def _build_ocr_cache_namespace(file_path: Path, settings: Settings, render_dpi: int) -> str:
    stat = file_path.stat()
    fingerprint = "|".join(
        [
            _OCR_CACHE_VERSION,
            str(file_path.resolve()),
            str(stat.st_size),
            str(stat.st_mtime_ns),
            settings.gemini_ocr_model,
            str(render_dpi),
        ]
    )
    return hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()


def _ocr_cache_path(settings: Settings, namespace: str, page_start: int, page_end: int) -> Path:
    return settings.resolve_ocr_cache_dir() / namespace / f"pages-{page_start:04d}-{page_end:04d}.json"


def _load_cached_ocr_batch(settings: Settings, namespace: str, page_start: int, page_end: int) -> list[str] | None:
    cache_path = _ocr_cache_path(settings, namespace, page_start, page_end)
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        cache_path.unlink(missing_ok=True)
        return None

    texts = payload.get("texts")
    expected_pages = page_end - page_start + 1
    if not isinstance(texts, list) or len(texts) != expected_pages:
        cache_path.unlink(missing_ok=True)
        return None
    normalized = [str(item or "") for item in texts]
    if not any(text.strip() for text in normalized):
        cache_path.unlink(missing_ok=True)
        return None
    return normalized


def _save_cached_ocr_batch(
    settings: Settings,
    namespace: str,
    page_start: int,
    page_end: int,
    texts: list[str],
) -> None:
    cache_path = _ocr_cache_path(settings, namespace, page_start, page_end)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "page_start": page_start,
        "page_end": page_end,
        "texts": [str(item or "") for item in texts],
    }
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _ocr_page_batch(client, types, genai_errors, settings: Settings, rendered_pages: list[dict], max_attempts: int) -> list[str]:
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.models.generate_content(
                model=settings.gemini_ocr_model,
                contents=[types.Content(role="user", parts=_build_ocr_parts(types, rendered_pages))],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=_OCR_RESPONSE_SCHEMA,
                    temperature=0,
                ),
            )
            payload = json.loads(response.text)
            return _normalize_ocr_payload(payload, rendered_pages)
        except (genai_errors.APIError, OSError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            if attempt >= max_attempts:
                error_details = {
                    "attempts": attempt,
                    "backend": "gemini_page_ocr",
                    "page_start": rendered_pages[0]["page_num"],
                    "page_end": rendered_pages[-1]["page_num"],
                    "message": str(exc),
                }
                if isinstance(exc, genai_errors.APIError):
                    error_details["code"] = exc.code
                raise AppError(
                    "OCR_REQUEST_FAILED",
                    "OCR API request failed",
                    status_code=502,
                    details=error_details,
                ) from exc
            time.sleep(min(2 * attempt, 5))

    raise AppError(
        "OCR_REQUEST_FAILED",
        "OCR API request failed",
        status_code=502,
        details={"backend": "gemini_page_ocr", "message": str(last_error) if last_error else "unknown"},
    )


def _build_ocr_parts(types, rendered_pages: list[dict]) -> list:
    parts = [types.Part.from_text(text=_OCR_INSTRUCTIONS)]
    for page in rendered_pages:
        parts.append(types.Part.from_text(text=f"Image for page {page['page_num']}"))
        parts.append(types.Part.from_bytes(data=page["image_bytes"], mime_type="image/png"))
    return parts


def _normalize_ocr_payload(payload: dict, rendered_pages: list[dict]) -> list[str]:
    pages = payload.get("pages") or []
    if len(pages) != len(rendered_pages):
        raise ValueError("OCR response page count mismatch")

    expected_page_nums = [page["page_num"] for page in rendered_pages]
    actual_page_nums: list[int] = []
    for item in pages:
        try:
            actual_page_nums.append(int(item.get("page_num")))
        except (TypeError, ValueError):
            actual_page_nums = []
            break

    if actual_page_nums and sorted(actual_page_nums) == sorted(expected_page_nums):
        indexed_pages = {int(item["page_num"]): item for item in pages}
        ordered_pages = [indexed_pages[page_num] for page_num in expected_page_nums]
    else:
        ordered_pages = pages

    normalized: list[str] = []
    for item in ordered_pages:
        page_text = str(item.get("page_text") or "").replace("\r\n", "\n").strip()
        normalized.append(page_text)
    return normalized
