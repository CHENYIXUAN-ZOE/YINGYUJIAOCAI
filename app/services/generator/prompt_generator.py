from __future__ import annotations

from app.schemas.content import Classification, UnitPrompt


def generate(classification: Classification, unit_id: str) -> UnitPrompt:
    return UnitPrompt(
        item_id=f"{unit_id}_prompt_1",
        classification=classification,
        unit_theme="介绍家庭成员",
        grammar_rules=[
            "使用 This is my ... 介绍人物关系",
            "使用 Who's this? 询问人物身份",
        ],
        prompt_notes=[
            "优先使用简短句子",
            "示例内容应围绕家庭照片场景",
        ],
        source_basis=[
            "来源于重点句型和对话样例",
            "来源于词汇中的家庭成员词",
        ],
    )
