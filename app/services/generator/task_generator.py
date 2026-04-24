from __future__ import annotations

from app.schemas.content import Classification, SentencePattern, UnitTask, VocabularyItem
from app.services.parser.heuristics import keyword_summary


def generate(
    classification: Classification,
    unit_id: str,
    *,
    unit_theme: str | None = None,
    vocabulary: list[VocabularyItem] | None = None,
    sentence_patterns: list[SentencePattern] | None = None,
) -> UnitTask:
    resolved_theme = unit_theme or classification.unit_name or classification.unit_code
    vocabulary = vocabulary or []
    sentence_patterns = sentence_patterns or []
    keywords = keyword_summary([item.word for item in vocabulary], limit=3)
    source_basis: list[str] = []
    if vocabulary:
        source_basis.append(f"核心词汇：{keywords}")
    if sentence_patterns:
        source_basis.append(f"重点句型：{sentence_patterns[0].pattern}")
    if not source_basis:
        source_basis.append(f"来源于单元主题：{resolved_theme}")

    return UnitTask(
        item_id=f"{unit_id}_task_1",
        classification=classification,
        task_intro=f"围绕“{resolved_theme}”进行基础口语问答与表达练习",
        source_basis=source_basis[:3],
    )
