from __future__ import annotations

from app.schemas.content import Classification, DialogueSample, SentencePattern, UnitPrompt, VocabularyItem
from app.services.parser.heuristics import keyword_summary


def generate(
    classification: Classification,
    unit_id: str,
    *,
    unit_theme: str | None = None,
    vocabulary: list[VocabularyItem] | None = None,
    sentence_patterns: list[SentencePattern] | None = None,
    dialogue_samples: list[DialogueSample] | None = None,
) -> UnitPrompt:
    resolved_theme = unit_theme or classification.unit_name or classification.unit_code
    vocabulary = vocabulary or []
    sentence_patterns = sentence_patterns or []
    dialogue_samples = dialogue_samples or []
    keywords = keyword_summary([item.word for item in vocabulary], limit=3)

    grammar_rules = [item.pattern for item in sentence_patterns[:3]]
    if not grammar_rules and keywords != "本单元主题":
        grammar_rules = [f"优先使用与 {keywords} 相关的短句表达"]
    if not grammar_rules:
        grammar_rules = [f"围绕“{resolved_theme}”组织简短句子"]

    prompt_notes = [f"对话内容保持围绕“{resolved_theme}”"]
    if keywords != "本单元主题":
        prompt_notes.append(f"尽量复用词汇：{keywords}")
    if dialogue_samples:
        prompt_notes.append("优先参考教材中的对话轮次与问答节奏")

    source_basis: list[str] = []
    if sentence_patterns:
        source_basis.append(f"来源于句型：{sentence_patterns[0].pattern}")
    if vocabulary:
        source_basis.append(f"来源于词汇：{keywords}")
    if dialogue_samples:
        source_basis.append(f"来源于对话：{dialogue_samples[0].title or resolved_theme}")
    if not source_basis:
        source_basis.append(f"来源于单元主题：{resolved_theme}")

    return UnitPrompt(
        item_id=f"{unit_id}_prompt_1",
        classification=classification,
        unit_theme=resolved_theme,
        grammar_rules=grammar_rules[:3],
        prompt_notes=prompt_notes[:3],
        source_basis=source_basis[:3],
    )
