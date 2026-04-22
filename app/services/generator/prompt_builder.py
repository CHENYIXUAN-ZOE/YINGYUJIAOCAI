from __future__ import annotations

import json

from app.schemas.content import Classification


def _trim_lines(lines: list[object], limit: int = 60, max_chars: int = 160) -> list[str]:
    trimmed: list[str] = []
    for raw_line in lines:
        line = str(raw_line or "").strip()
        if not line:
            continue
        trimmed.append(line[:max_chars])
        if len(trimmed) >= limit:
            break
    return trimmed


def _json_block(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def build_unit_generation_prompt(classification: Classification, raw_unit: dict, source_text: str) -> str:
    candidate_theme = raw_unit.get("unit_theme") or classification.unit_name
    evidence_payload = {
        "classification": classification.model_dump(),
        "candidate_unit_theme": candidate_theme,
        "source_pages": raw_unit.get("source_pages", []),
        "source_line_samples": _trim_lines(raw_unit.get("lines", [])),
        "source_text": source_text,
    }

    return f"""
你是小学英语教材结构化助手。你的任务是把“当前单元的解析证据”整理成教材内容产出工具可直接消费的结构化 JSON。

通用生成原则：
1. 只处理当前 classification 对应的单元，不得混入其他单元、其他章节或整册级知识点。
2. 只能依据输入中的解析证据做抽取、规范化或最小幅度推导；没有依据的核心知识点不要编造。
3. 输出必须严格匹配目标 JSON 字段；不要输出解释、Markdown、代码块或额外字段。
4. 无法确认的非核心细节可以留空字符串，但不要伪造来源；`vocabulary`、`sentence_patterns`、`dialogue_samples` 不要返回空数组，证据较少时只保留最稳妥的少量结果。
5. 所有内容都必须与当前 classification 一致；英文保持自然、简洁、适合小学英语教材，中文只写直接释义或简短说明。
6. `source_basis` 只总结你实际使用到的单元标题、词汇、句型、对话或场景依据，不要写空泛套话。

输出合同：
- 顶层只输出一个 JSON object。
- 顶层字段固定为：`unit_theme`, `vocabulary`, `sentence_patterns`, `dialogue_samples`, `unit_task`, `unit_prompt`。
- `vocabulary` 中每项固定字段：`word`, `part_of_speech`, `meaning_zh`, `example_sentences`, `source_excerpt`。
- `sentence_patterns` 中每项固定字段：`pattern`, `usage_note`, `examples`, `source_excerpt`。
- `dialogue_samples` 中每项固定字段：`title`, `source_excerpt`, `turns`；每个 turn 固定字段：`speaker`, `text_en`, `text_zh`。
- `unit_task` 固定字段：`task_intro`, `source_basis`。
- `unit_prompt` 固定字段：`unit_theme`, `grammar_rules`, `prompt_notes`, `source_basis`。

板块约束：
1. `vocabulary`
- 优先输出当前单元最核心、最稳定、最适合教学展示的词汇，建议 8-15 个；证据不足时可以更少，但不要超过 20 个。
- 不新增教材中没有依据的核心词汇。
- `example_sentences` 每项输出 1-2 句，优先保留教材原句；若原文只有短语，可做最小幅度补成简单句。
- `part_of_speech` 尽量使用短格式，如 `n.` `v.` `adj.` `pron.` `prep.`。

2. `sentence_patterns`
- 只保留当前单元教学核心句型，优先输出 3-5 个；教材显式句型不足时按实际数量输出。
- 每个句型的 `examples` 必须为 1-2 句，且尽量贴合当前单元主题。
- 不要把普通陈述句、零散长句或超出当前单元水平的表达误判成重点句型。

3. `dialogue_samples`
- 默认输出 1 个主对话样例。
- 对话必须为 10-15 轮，每轮都必须包含 `speaker`, `text_en`, `text_zh`。
- 优先整理教材已有对话；如果现有对话轮次不足，可以基于当前单元词汇、句型和场景做最小幅度补足。
- `text_zh` 只写对应英文的直接中文释义，不要额外扩写。
- 对话尽量覆盖至少 2 个重点句型和 4 个核心词汇。

4. `unit_task`
- 只输出 1 条任务介绍。
- `task_intro` 用一句短话概括“学生在本单元主要做什么”，目标 15-30 个中文字符，理想值约 20 个。
- 不要写成“提高英语能力”“掌握英语知识”这类空泛口号。

5. `unit_prompt`
- `unit_theme` 用短词组或短句概括当前单元主题。
- `grammar_rules` 输出 1-3 条，只保留当前单元最相关的语法规则；不要做整册级大总结。
- `prompt_notes` 输出 0-3 条补充提示，聚焦表达场景、句子长度、语用注意点等当前单元信息。

当前单元证据：
```json
{_json_block(evidence_payload)}
```

请只输出符合要求的 JSON，不要附加任何解释。
""".strip()
