from __future__ import annotations

import re
from collections.abc import Iterable

UNIT_HEADER_PATTERNS = (
    re.compile(r"^(Unit)\s*([0-9]+|[A-Z])(?:\s*[:.\-])?\s*(.*)$", re.IGNORECASE),
    re.compile(r"^(Revision)\s*([0-9]+|[A-Z])(?:\s*[:.\-])?\s*(.*)$", re.IGNORECASE),
    re.compile(r"^(Module)\s*([0-9]+|[A-Z])(?:\s*[:.\-])?\s*(.*)$", re.IGNORECASE),
    re.compile(r"^第?\s*([一二三四五六七八九十0-9]+)\s*单元(?:\s*[:：.\-])?\s*(.*)$"),
)

SECTION_TITLES = {
    "words",
    "word",
    "vocabulary",
    "pattern",
    "patterns",
    "sentence",
    "sentences",
    "dialogue",
    "dialog",
    "conversation",
}

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "be",
    "can",
    "do",
    "for",
    "from",
    "he",
    "her",
    "his",
    "i",
    "in",
    "is",
    "it",
    "let",
    "lets",
    "me",
    "my",
    "of",
    "our",
    "she",
    "talk",
    "the",
    "their",
    "them",
    "there",
    "they",
    "this",
    "to",
    "unit",
    "we",
    "what",
    "where",
    "who",
    "why",
    "you",
    "your",
}

POS_TAG_PATTERN = re.compile(r"\b(n|v|adj|adv|prep|conj|pron|num|art|aux)\.$", re.IGNORECASE)
SPEAKER_PATTERN = re.compile(r"^([A-Z][A-Za-z]{0,11}|[A-Z])\s*[:：]\s*(.+)$")
ENGLISH_TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z'\-]{1,}")
PRINTED_PAGE_PATTERN = re.compile(r"(?:^|\s)([0-9]{1,3})\s*$")
APPENDIX_TITLE_PATTERN = re.compile(
    r"(?i)\b(progress\s*check|uncle\s*becky'?s\s*abc|vocabulary|word\s*list|masks)\b"
)


def normalize_unit_header_candidate(text: str) -> str:
    normalized = normalize_line(text)
    replacements = {
        r"(?i)\bU\s*N\s*I\s*T\b": "Unit",
        r"(?i)\bR\s*E\s*V\s*I\s*S\s*I\s*O\s*N\b": "Revision",
        r"(?i)\bM\s*O\s*D\s*U\s*L\s*E\b": "Module",
    }
    for pattern, replacement in replacements.items():
        normalized = re.sub(pattern, replacement, normalized)
    return normalized


def normalize_line(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", text.replace("\x00", " ")).strip()
    return collapsed.strip("-*#|")


def unique_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        key = value.casefold()
        if not value or key in seen:
            continue
        seen.add(key)
        unique.append(value)
    return unique


def extract_english_tokens(text: str) -> list[str]:
    return ENGLISH_TOKEN_PATTERN.findall(text)


def looks_like_unit_header(line: str) -> tuple[str, str, str] | None:
    normalized = normalize_unit_header_candidate(line)
    if not normalized:
        return None
    if "Unit" in normalized:
        normalized = normalized[normalized.index("Unit") :]
    elif "Revision" in normalized:
        normalized = normalized[normalized.index("Revision") :]
    elif "Module" in normalized:
        normalized = normalized[normalized.index("Module") :]
    for pattern in UNIT_HEADER_PATTERNS:
        match = pattern.match(normalized)
        if not match:
            continue
        groups = match.groups()
        if len(groups) == 3:
            kind, code, name = groups
            return kind.title(), str(code).strip(), normalize_line(name)
        code, name = groups
        return "Unit", str(code).strip(), normalize_line(name)
    return None


def extract_printed_page_number(line: str) -> int | None:
    normalized = normalize_unit_header_candidate(line)
    match = PRINTED_PAGE_PATTERN.search(normalized)
    if not match:
        return None
    return int(match.group(1))


def strip_trailing_page_number(text: str) -> str:
    normalized = normalize_line(text)
    return normalize_line(re.sub(r"\s+[0-9]{1,3}$", "", normalized))


def is_appendix_title(line: str) -> bool:
    return bool(APPENDIX_TITLE_PATTERN.search(normalize_unit_header_candidate(line)))


def strip_section_label(line: str) -> tuple[str | None, str]:
    normalized = normalize_line(line)
    match = re.match(r"^([A-Za-z]+)\s*[:：]\s*(.+)$", normalized)
    if not match:
        return None, normalized
    label = match.group(1).lower()
    remainder = normalize_line(match.group(2))
    if label in SECTION_TITLES:
        return label, remainder
    return None, normalized


def score_theme(text: str) -> int:
    english_tokens = extract_english_tokens(text)
    if not english_tokens:
        return 0
    if len(english_tokens) > 7:
        return 0
    return len(english_tokens) * 2 + min(len(text), 20)


def infer_theme(unit_name: str | None, lines: list[str]) -> str | None:
    if unit_name:
        return unit_name
    ranked = sorted(
        (
            (score_theme(line), line)
            for line in lines
            if line and not strip_section_label(line)[0] and not SPEAKER_PATTERN.match(line)
        ),
        reverse=True,
    )
    for score, line in ranked:
        if score <= 0:
            break
        return line
    return None


def parse_speaker_line(line: str) -> tuple[str, str] | None:
    match = SPEAKER_PATTERN.match(normalize_line(line))
    if not match:
        return None
    speaker, content = match.groups()
    return speaker, normalize_line(content)


def infer_usage_note(pattern: str) -> str:
    normalized = pattern.strip()
    lowered = normalized.lower()
    if normalized.endswith("?"):
        return "核心问句"
    if "..." in normalized:
        return "替换练习句型"
    if lowered.startswith(("this is", "that is", "he is", "she is", "i am", "we are")):
        return "核心陈述句"
    return "单元重点表达"


def keyword_summary(words: list[str], limit: int = 3) -> str:
    filtered = [word for word in unique_preserve_order(words) if word.casefold() not in STOPWORDS]
    if not filtered:
        return "本单元主题"
    return "、".join(filtered[:limit])
