from __future__ import annotations

import re
import shutil
import subprocess
import zlib
from pathlib import Path

from app.services.parser.heuristics import normalize_line


STREAM_PATTERN = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.DOTALL)
TEXT_SHOW_PATTERN = re.compile(r"\((?:\\.|[^\\()])*\)\s*Tj")
TEXT_ARRAY_PATTERN = re.compile(r"\[(.*?)\]\s*TJ", re.DOTALL)
STRING_PATTERN = re.compile(r"\((?:\\.|[^\\()])*\)")


def _is_pdf_octal_digit(char: str) -> bool:
    return char in "01234567"


def _decode_pdf_string(token: str) -> str:
    content = token[1:-1]
    decoded_chars: list[str] = []
    index = 0
    while index < len(content):
        char = content[index]
        if char != "\\":
            decoded_chars.append(char)
            index += 1
            continue

        index += 1
        if index >= len(content):
            break
        escaped = content[index]
        mapping = {
            "n": "\n",
            "r": "\r",
            "t": "\t",
            "b": "\b",
            "f": "\f",
            "(": "(",
            ")": ")",
            "\\": "\\",
        }
        if escaped in mapping:
            decoded_chars.append(mapping[escaped])
            index += 1
            continue

        if _is_pdf_octal_digit(escaped):
            octal = escaped
            for _ in range(2):
                if index + 1 < len(content) and _is_pdf_octal_digit(content[index + 1]):
                    index += 1
                    octal += content[index]
                else:
                    break
            decoded_chars.append(chr(int(octal, 8)))
            index += 1
            continue

        decoded_chars.append(escaped)
        index += 1
    return normalize_line("".join(decoded_chars))


def _decode_stream(stream: bytes) -> str:
    for candidate in (stream.strip(b"\r\n"), stream):
        if not candidate:
            continue
        decoded_bytes = candidate
        try:
            decoded_bytes = zlib.decompress(candidate)
        except zlib.error:
            pass
        for encoding in ("utf-8", "latin-1"):
            try:
                return decoded_bytes.decode(encoding)
            except UnicodeDecodeError:
                continue
    return ""


def _extract_stream_text(stream_text: str) -> str:
    segments: list[str] = []
    for match in TEXT_SHOW_PATTERN.finditer(stream_text):
        token = match.group(0).rsplit(" ", 1)[0]
        decoded = _decode_pdf_string(token)
        if decoded:
            segments.append(decoded)

    for match in TEXT_ARRAY_PATTERN.finditer(stream_text):
        tokens = [_decode_pdf_string(token) for token in STRING_PATTERN.findall(match.group(1))]
        text = normalize_line(" ".join(token for token in tokens if token))
        if text:
            segments.append(text)

    return "\n".join(segments)


def _extract_text_blocks(raw_bytes: bytes) -> list[str]:
    blocks = []
    for match in STREAM_PATTERN.finditer(raw_bytes):
        stream_text = _decode_stream(match.group(1))
        extracted = _extract_stream_text(stream_text)
        if extracted:
            blocks.append(extracted)
    return blocks


def _extract_pages_with_pdftotext(file_path: Path) -> list[str]:
    if not shutil.which("pdftotext"):
        return []

    try:
        completed = subprocess.run(
            ["pdftotext", "-layout", str(file_path), "-"],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []

    text = completed.stdout.decode("utf-8", "ignore")
    pages = [page for page in text.split("\f")]
    while pages and not pages[-1].strip():
        pages.pop()
    return pages


def load_pdf(file_path: Path) -> dict:
    raw_bytes = file_path.read_bytes()
    page_texts = _extract_pages_with_pdftotext(file_path)
    extractor = "pdftotext"
    if not page_texts:
        page_texts = _extract_text_blocks(raw_bytes)
        extractor = "raw_stream"

    page_lines: list[dict] = []
    lines: list[str] = []
    for page_num, page_text in enumerate(page_texts, start=1):
        normalized_lines = [normalize_line(line) for line in page_text.splitlines() if normalize_line(line)]
        for line in normalized_lines:
            page_lines.append({"page_num": page_num, "line": line})
        lines.extend(normalized_lines)

    return {
        "file_name": file_path.name,
        "stem": file_path.stem,
        "file_path": str(file_path),
        "size_bytes": len(raw_bytes),
        "page_texts": page_texts,
        "page_lines": page_lines,
        "text": "\n".join(page_texts),
        "lines": lines,
        "extractor": extractor,
    }
