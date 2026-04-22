from __future__ import annotations


def analyze(document: dict) -> dict:
    page_texts = document.get("page_texts") or []
    if page_texts:
        document["pages"] = list(range(1, len(page_texts) + 1))
        document["page_count"] = len(page_texts)
        return document

    page_lines = document.get("page_lines") or []
    if page_lines:
        pages = sorted({int(item.get("page_num", 1)) for item in page_lines})
        document["pages"] = pages
        document["page_count"] = len(pages)
        return document

    document["pages"] = [1]
    document["page_count"] = 1
    return document
