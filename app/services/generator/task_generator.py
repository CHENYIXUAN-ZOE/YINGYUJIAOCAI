from __future__ import annotations

from app.schemas.content import Classification, UnitTask


def generate(classification: Classification, unit_id: str) -> UnitTask:
    return UnitTask(
        item_id=f"{unit_id}_task_1",
        classification=classification,
        task_intro="围绕家庭成员进行基础介绍",
        source_basis=[
            "单元词汇涉及家庭成员",
            "重点句型围绕人物身份介绍",
        ],
    )
