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


def _fallback_unit(stem: str, page_map: dict[int, list[str]]) -> list[dict]:
    fallback_name = stem[:18] if stem else "教材单元"
    lines: list[str] = []
    source_pages: list[int] = []
    for page_num in sorted(page_map):
        source_pages.append(page_num)
        lines.extend(page_map[page_num])
    return [
        _finalize_unit(
            {
                "unit_code": "Unit 1",
                "unit_name": fallback_name,
                "unit_theme": fallback_name,
                "source_pages": source_pages or [1],
                "lines": lines,
            }
        )
    ]


def _group_page_lines(document: dict, *, prefer_filtered: bool = True) -> dict[int, list[str]]:
    grouped: dict[int, list[str]] = defaultdict(list)
    page_lines_source = "content_page_lines" if prefer_filtered else "page_lines"
    page_lines = document.get(page_lines_source) or document.get("page_lines") or []
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
        printed_start_page = _find_nearby_printed_page(lines, index)
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


def _scan_direction_for_printed_page(lines: list[str], start_index: int, step: int, *, limit: int = 4) -> int | None:
    for offset in range(1, limit + 1):
        candidate_index = start_index + step * offset
        if candidate_index < 0 or candidate_index >= len(lines):
            break
        candidate_line = lines[candidate_index]
        if looks_like_unit_header(candidate_line):
            break
        printed_page = extract_printed_page_number(candidate_line)
        if printed_page is not None:
            return printed_page
    return None


def _find_nearby_printed_page(lines: list[str], index: int) -> int | None:
    current_line_page = extract_printed_page_number(lines[index])
    if current_line_page is not None:
        return current_line_page

    previous_line_page = _scan_direction_for_printed_page(lines, index, -1)
    if previous_line_page is not None:
        return previous_line_page

    return _scan_direction_for_printed_page(lines, index, 1)


def _toc_pages(page_map: dict[int, list[str]]) -> set[int]:
    return {page_num for page_num, lines in page_map.items() if len(_scan_toc_entries(page_num, lines)) >= 2}


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


def _pick_page_header(lines: list[str]) -> tuple[str, str, str] | None:
    candidates: list[tuple[int, tuple[str, str, str]]] = []
    for index, line in enumerate(lines[:8]):
        header = looks_like_unit_header(line)
        if not header:
            continue
        score = 30 - index * 4
        if extract_printed_page_number(line) is not None:
            score -= 8
        if header[2]:
            score += 2
        candidates.append((score, header))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _detect_from_body(page_map: dict[int, list[str]]) -> list[dict]:
    units: list[dict] = []
    current: dict | None = None
    toc_pages = _toc_pages(page_map)

    for page_num in sorted(page_map):
        lines = page_map[page_num]
        if page_num in toc_pages:
            continue
        if lines and is_appendix_title(lines[0]):
            if current:
                units.append(_finalize_unit(current))
                current = None
            continue

        page_header = _pick_page_header(lines)
        if page_header:
            kind, code, name = page_header
            next_unit_code = f"{kind} {code}"
            if current and current["unit_code"] == next_unit_code:
                current["source_pages"].append(page_num)
                current["lines"].extend(lines)
                continue
            if current:
                units.append(_finalize_unit(current))
            current = {
                "unit_code": next_unit_code,
                "unit_name": name or next_unit_code,
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
    return units


def _score_units(units: list[dict], num_pages: int, *, prefer_front_start: bool) -> int:
    if not units:
        return -10_000
    starts = [unit["source_pages"][0] for unit in units if unit.get("source_pages")]
    if not starts:
        return -10_000
    score = len(units) * 10
    if starts == sorted(starts):
        score += 10
    else:
        score -= 20
    if prefer_front_start:
        score += 6 if starts[0] <= max(12, num_pages // 3) + 2 else -8
    else:
        score += 4 if starts[0] <= max(20, num_pages // 2) else -4
    if len(units) == 1 and num_pages >= 20:
        score -= 25
    coverage = sum(max(1, len(unit.get("source_pages", []))) for unit in units)
    if coverage >= max(2, num_pages // 2):
        score += 5
    return score


def detect(document: dict) -> list[dict]:
    stem = document.get("stem", "教材")
    content_page_map = _group_page_lines(document, prefer_filtered=True)
    raw_page_map = _group_page_lines(document, prefer_filtered=False)
    page_map = content_page_map or raw_page_map
    num_pages = document.get("page_count") or (max(raw_page_map or page_map) if (raw_page_map or page_map) else max(len(document.get("page_texts", [])), 1))

    toc_units = _detect_toc_units(raw_page_map or page_map, num_pages)
    body_units = _detect_from_body(page_map)

    toc_score = _score_units(toc_units, num_pages, prefer_front_start=True)
    body_score = _score_units(body_units, num_pages, prefer_front_start=False)

    if toc_units and toc_score >= body_score:
        return toc_units
    if body_units:
        return body_units
    if toc_units:
        return toc_units
    return _fallback_unit(stem, page_map)
