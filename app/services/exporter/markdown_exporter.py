from __future__ import annotations

from pathlib import Path


def export_markdown(payload: dict, output_path: Path) -> Path:
    book = payload["book"]
    lines = [
        f"# {book['textbook_name']}",
        "",
        f"- 教材版本：{book['textbook_version']}",
        "",
    ]
    for unit_package in payload["units"]:
        unit = unit_package["unit"]
        lines.append(f"## {unit['classification']['unit_code']} {unit['classification']['unit_name']}")
        lines.append("")
        lines.append("### 词汇")
        for item in unit_package["vocabulary"]:
            lines.append(f"- {item['word']} | {item.get('part_of_speech') or ''} | {item.get('meaning_zh') or ''}")
        lines.append("")
        lines.append("### 重点句型")
        for item in unit_package["sentence_patterns"]:
            lines.append(f"- {item['pattern']}")
            for example in item.get("examples", []):
                lines.append(f"  - {example}")
        lines.append("")
        lines.append("### 对话样例")
        for dialogue in unit_package["dialogue_samples"]:
            lines.append(f"- {dialogue.get('title') or 'Dialogue'}")
            for turn in dialogue["turns"]:
                lines.append(f"  - {turn['speaker']}: {turn['text_en']} / {turn['text_zh']}")
        lines.append("")
        lines.append("### 单元任务介绍")
        lines.append(f"- {unit_package['unit_task']['task_intro']}")
        lines.append("")
        lines.append("### 提示")
        lines.append(f"- 主题：{unit_package['unit_prompt']['unit_theme']}")
        for rule in unit_package["unit_prompt"]["grammar_rules"]:
            lines.append(f"  - 语法：{rule}")
        lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path
