from __future__ import annotations

from collections import defaultdict

from app.services.parser.heuristics import (
    extract_printed_page_number,
    infer_theme,
    is_appendix_title,
    looks_like_unit_header,
    normalize_line,
    strip_trailing_page_number,
)


def _finalize_unit(unit: dict) -> dict:
    unit["lines"] = [normalize_line(line) for line in unit.get("lines", []) if normalize_line(line)]
    unit["source_pages"] = sorted(set(unit.get("source_pages", [1])))
    unit["text"] = "\n".join(unit["lines"])
    unit["unit_theme"] = infer_theme(unit.get("unit_name"), unit["lines"])
    return unit


def _fallback_unit(stem: str) -> list[dict]:
    fallback_name = stem[:18] if stem else "教材单元"
    return [
        {
            "unit_code": "Unit 1",
            "unit_name": fallback_name,
            "unit_theme": fallback_name,
            "source_pages": [1],
            "lines": [],
            "text": "",
        }
    ]


def _group_page_lines(document: dict) -> dict[int, list[str]]:
    grouped: dict[int, list[str]] = defaultdict(list)
    page_lines = document.get("page_lines") or []
    for item in page_lines:
        page_num = int(item.get("page_num", 1))
        line = normalize_line(item.get("line", ""))
        if line:
            grouped[page_num].append(line)
    if grouped:
        return dict(grouped)

    lines = [normalize_line(line) for line in document.get("lines", []) if normalize_line(line)]
    return {1: lines}


def _scan_toc_entries(page_num: int, lines: list[str]) -> list[dict]:
    entries: list[dict] = []
    for index, line in enumerate(lines):
        header = looks_like_unit_header(line)
        if not header:
            continue
        kind, code, name = header
        printed_start_page = extract_printed_page_number(line)
        if printed_start_page is None:
            for offset in range(1, 3):
                next_index = index + offset
                if next_index >= len(lines):
                    break
                next_line = lines[next_index]
                if looks_like_unit_header(next_line):
                    break
                printed_start_page = extract_printed_page_number(next_line)
                if printed_start_page is not None:
                    break
        if printed_start_page is None:
            continue
        cleaned_name = strip_trailing_page_number(name or f"{kind} {code}")
        entries.append(
            {
                "page_num": page_num,
                "kind": kind,
                "code": code,
                "name": cleaned_name or f"{kind} {code}",
                "printed_start_page": printed_start_page,
            }
        )
    deduped: list[dict] = []
    seen: set[tuple[str, str, int]] = set()
    for entry in entries:
        key = (entry["kind"], entry["code"], entry["printed_start_page"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped


def _detect_toc_units(page_map: dict[int, list[str]], num_pages: int) -> list[dict]:
    toc_candidates: list[tuple[int, list[dict]]] = []
    for page_num, lines in page_map.items():
        entries = _scan_toc_entries(page_num, lines)
        if len(entries) >= 2:
            toc_candidates.append((page_num, entries))

    if not toc_candidates:
        return []

    toc_candidates.sort(key=lambda item: item[0])
    front_matter_limit = max(12, num_pages // 3)
    clusters: list[list[tuple[int, list[dict]]]] = []
    for candidate in toc_candidates:
        if not clusters or candidate[0] - clusters[-1][-1][0] > 2:
            clusters.append([candidate])
        else:
            clusters[-1].append(candidate)

    selected_cluster = next((cluster for cluster in clusters if cluster[0][0] <= front_matter_limit), clusters[0])
    toc_page_entries = {page_num: entries for page_num, entries in selected_cluster}

    appendix_boundaries: list[int] = []
    for page_num, lines in page_map.items():
        if page_num not in toc_page_entries:
            continue
        for index, line in enumerate(lines):
            if not is_appendix_title(line):
                continue
            for offset in range(0, 3):
                next_index = index + offset
                if next_index >= len(lines):
                    break
                printed_page = extract_printed_page_number(lines[next_index])
                if printed_page is not None:
                    appendix_boundaries.append(printed_page)
                    break

    toc_entries = sorted(
        {
            (entry["kind"], entry["code"], entry["name"], entry["printed_start_page"])
            for entries in toc_page_entries.values()
            for entry in entries
        },
        key=lambda item: item[3],
    )
    if len(toc_entries) < 2:
        return []

    toc_end_page = max(toc_page_entries)
    first_printed_start = toc_entries[0][3]
    page_offset = toc_end_page + 1 - first_printed_start

    appendix_physical_pages = sorted(
        printed_page + page_offset
        for printed_page in appendix_boundaries
        if printed_page + page_offset > toc_end_page
    )
    book_end_page = appendix_physical_pages[0] - 1 if appendix_physical_pages else num_pages

    units: list[dict] = []
    for index, (kind, code, name, printed_start_page) in enumerate(toc_entries):
        physical_start = printed_start_page + page_offset
        if physical_start < 1 or physical_start > num_pages:
            continue
        next_physical_start = (
            toc_entries[index + 1][3] + page_offset if index + 1 < len(toc_entries) else book_end_page + 1
        )
        physical_end = min(next_physical_start - 1, book_end_page)
        if physical_end < physical_start:
            physical_end = physical_start

        lines: list[str] = []
        source_pages: list[int] = []
        for page_num in range(physical_start, physical_end + 1):
            lines.extend(page_map.get(page_num, []))
            source_pages.append(page_num)

        units.append(
            _finalize_unit(
                {
                    "unit_code": f"{kind} {code}",
                    "unit_name": name,
                    "unit_theme": name,
                    "source_pages": source_pages,
                    "lines": lines,
                }
            )
        )
    return units


def _detect_from_body(page_map: dict[int, list[str]], stem: str) -> list[dict]:
    units: list[dict] = []
    current: dict | None = None

    toc_pages = {page_num for page_num, lines in page_map.items() if len(_scan_toc_entries(page_num, lines)) >= 2}

    for page_num in sorted(page_map):
        lines = page_map[page_num]
        if page_num in toc_pages:
            continue

        page_header = next((looks_like_unit_header(line) for line in lines if looks_like_unit_header(line)), None)
        if page_header:
            if current:
                units.append(_finalize_unit(current))
            kind, code, name = page_header
            current = {
                "unit_code": f"{kind} {code}",
                "unit_name": name or f"{kind} {code}",
                "unit_theme": name or None,
                "source_pages": [page_num],
                "lines": list(lines),
            }
            continue

        if current is None:
            continue
        current["source_pages"].append(page_num)
        current["lines"].extend(lines)

    if current:
        units.append(_finalize_unit(current))

    if units:
        return units

    current = {
        "unit_code": "Unit 1",
        "unit_name": stem[:18] if stem else "教材单元",
        "unit_theme": None,
        "source_pages": [],
        "lines": [],
    }
    for page_num in sorted(page_map):
        current["source_pages"].append(page_num)
        current["lines"].extend(page_map[page_num])
    return [_finalize_unit(current)]

def detect(document: dict) -> list[dict]:
    stem = document.get("stem", "教材")
    page_map = _group_page_lines(document)
    num_pages = max(page_map) if page_map else max(len(document.get("page_texts", [])), 1)

    toc_units = _detect_toc_units(page_map, num_pages)
    if toc_units:
        return toc_units

    body_units = _detect_from_body(page_map, stem)
    if body_units:
        return body_units

    return _fallback_unit(stem)
