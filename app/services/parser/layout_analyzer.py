from __future__ import annotations

from collections import defaultdict

from app.services.parser.heuristics import canonicalize_repeat_line, classify_section_heading, looks_like_unit_header


def _group_page_lines(document: dict) -> dict[int, list[str]]:
    grouped: dict[int, list[str]] = defaultdict(list)
    for item in document.get("page_lines") or []:
        try:
            page_num = int(item.get("page_num", 1))
        except (TypeError, ValueError):
            page_num = 1
        line = str(item.get("line") or "").strip()
        if line:
            grouped[page_num].append(line)
    return dict(grouped)


def _is_repeating_ornament(line: str, page_hits: set[int], page_count: int) -> bool:
    if not line:
        return False
    if len(page_hits) < (2 if page_count < 8 else 3):
        return False
    if looks_like_unit_header(line) or classify_section_heading(line):
        return False
    if len(line) > 40 or len(line.split()) > 8:
        return False
    return True


def _extract_repeated_lines(page_map: dict[int, list[str]], page_count: int) -> tuple[set[str], list[str]]:
    key_to_pages: dict[str, set[int]] = defaultdict(set)
    key_to_sample: dict[str, str] = {}
    for page_num, lines in page_map.items():
        seen_on_page: set[str] = set()
        for line in lines:
            key = canonicalize_repeat_line(line)
            if not key or key in seen_on_page:
                continue
            seen_on_page.add(key)
            key_to_pages[key].add(page_num)
            key_to_sample.setdefault(key, line)

    repeated_keys = {
        key
        for key, pages in key_to_pages.items()
        if _is_repeating_ornament(key_to_sample.get(key, ""), pages, page_count)
    }
    repeated_lines = [key_to_sample[key] for key in sorted(repeated_keys)]
    return repeated_keys, repeated_lines


def _filter_page_lines(page_map: dict[int, list[str]], repeated_keys: set[str]) -> list[dict]:
    filtered: list[dict] = []
    for page_num in sorted(page_map):
        for line in page_map[page_num]:
            if canonicalize_repeat_line(line) in repeated_keys:
                continue
            filtered.append({"page_num": page_num, "line": line})
    return filtered


def analyze(document: dict) -> dict:
    page_texts = document.get("page_texts") or []
    page_map = _group_page_lines(document)
    if page_texts:
        document["pages"] = list(range(1, len(page_texts) + 1))
        document["page_count"] = len(page_texts)
    elif page_map:
        pages = sorted(page_map)
        document["pages"] = pages
        document["page_count"] = len(pages)
    else:
        document["pages"] = [1]
        document["page_count"] = 1

    repeated_keys, repeated_lines = _extract_repeated_lines(page_map, document["page_count"])
    filtered_page_lines = _filter_page_lines(page_map, repeated_keys) if page_map else list(document.get("page_lines") or [])
    document["content_page_lines"] = filtered_page_lines
    document["layout"] = {
        "page_count": document["page_count"],
        "repeated_lines": repeated_lines,
        "filtered_page_lines": filtered_page_lines,
    }
    return document
