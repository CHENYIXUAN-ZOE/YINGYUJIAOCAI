from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape


INVALID_XML_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")
INVALID_SHEET_CHARS_RE = re.compile(r"[\[\]:*?/\\]")


def _clean_xml_text(value: object) -> str:
    text = "" if value is None else str(value)
    return INVALID_XML_RE.sub("", text)


def _column_letter(index: int) -> str:
    letters: list[str] = []
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters.append(chr(65 + remainder))
    return "".join(reversed(letters))


def _make_sheet_name(name: str, used_names: set[str]) -> str:
    cleaned = INVALID_SHEET_CHARS_RE.sub(" ", name).strip() or "Sheet"
    cleaned = cleaned[:31]
    candidate = cleaned
    suffix = 1
    while candidate in used_names:
        label = f"_{suffix}"
        candidate = f"{cleaned[: 31 - len(label)]}{label}"
        suffix += 1
    used_names.add(candidate)
    return candidate


def _build_sheet_xml(rows: list[list[object]]) -> str:
    xml_rows: list[str] = []
    for row_index, row in enumerate(rows, start=1):
        cells: list[str] = []
        for col_index, value in enumerate(row, start=1):
            cell_ref = f"{_column_letter(col_index)}{row_index}"
            style = ' s="1"' if row_index == 1 else ""
            text = escape(_clean_xml_text(value))
            cells.append(
                f'<c r="{cell_ref}" t="inlineStr"{style}><is><t xml:space="preserve">{text}</t></is></c>'
            )
        xml_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    sheet_data = "".join(xml_rows) or '<row r="1"></row>'
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"/></sheetViews>'
        '<sheetFormatPr defaultRowHeight="15"/>'
        f"<sheetData>{sheet_data}</sheetData>"
        "</worksheet>"
    )


def _join(values: list[object], separator: str = " / ") -> str:
    return separator.join(str(value) for value in values if value not in (None, ""))


def _join_pages(pages: list[int]) -> str:
    return ", ".join(str(page) for page in pages)


def _build_workbook_sheets(payload: dict) -> list[tuple[str, list[list[object]]]]:
    book = payload["book"]
    units = payload.get("units", [])
    review_records = payload.get("review_records", [])
    textbook_name = book.get("textbook_name", "")
    textbook_version = book.get("textbook_version", "")

    vocabulary_rows = [[
        "教材名称",
        "教材版本",
        "单元编码",
        "单元名称",
        "单词",
        "词性",
        "解释",
        "例句",
        "美音",
        "英音",
        "来源页",
        "原文摘录",
        "审核状态",
    ]]
    sentence_rows = [[
        "教材名称",
        "教材版本",
        "单元编码",
        "单元名称",
        "句型",
        "用法说明",
        "例句",
        "来源页",
        "原文摘录",
        "审核状态",
    ]]
    dialogue_rows = [[
        "教材名称",
        "教材版本",
        "单元编码",
        "单元名称",
        "标题",
        "轮次数",
        "来源页",
        "原文摘录",
        "审核状态",
    ]]
    dialogue_turn_rows = [[
        "教材名称",
        "教材版本",
        "单元编码",
        "单元名称",
        "对话标题",
        "轮次",
        "角色",
        "英文",
        "中文",
        "审核状态",
    ]]
    unit_rows = [[
        "教材名称",
        "教材版本",
        "单元编码",
        "单元名称",
        "单元主题",
        "来源页",
        "词汇数量",
        "句型数量",
        "对话数量",
        "任务介绍",
        "生成主题",
        "审核状态",
    ]]
    task_rows = [[
        "教材名称",
        "教材版本",
        "单元编码",
        "单元名称",
        "任务介绍",
        "来源依据",
        "审核状态",
    ]]
    prompt_rows = [[
        "教材名称",
        "教材版本",
        "单元编码",
        "单元名称",
        "单元主题",
        "语法规则",
        "提示说明",
        "来源依据",
        "审核状态",
    ]]

    for unit_package in units:
        unit = unit_package["unit"]
        classification = unit["classification"]
        unit_code = classification["unit_code"]
        unit_name = classification["unit_name"]

        unit_rows.append(
            [
                textbook_name,
                textbook_version,
                unit_code,
                unit_name,
                unit.get("unit_theme") or unit_name,
                _join_pages(unit.get("source_pages", [])),
                len(unit_package.get("vocabulary", [])),
                len(unit_package.get("sentence_patterns", [])),
                len(unit_package.get("dialogue_samples", [])),
                unit_package["unit_task"].get("task_intro", ""),
                unit_package["unit_prompt"].get("unit_theme", ""),
                unit.get("review_status", ""),
            ]
        )

        for item in unit_package.get("vocabulary", []):
            vocabulary_rows.append(
                [
                    textbook_name,
                    textbook_version,
                    unit_code,
                    unit_name,
                    item.get("word", ""),
                    item.get("part_of_speech", ""),
                    item.get("meaning_zh", ""),
                    _join(item.get("example_sentences", [])),
                    "",
                    "",
                    _join_pages(item.get("source_pages", [])),
                    item.get("source_excerpt", ""),
                    item.get("review_status", ""),
                ]
            )

        for item in unit_package.get("sentence_patterns", []):
            sentence_rows.append(
                [
                    textbook_name,
                    textbook_version,
                    unit_code,
                    unit_name,
                    item.get("pattern", ""),
                    item.get("usage_note", ""),
                    _join(item.get("examples", [])),
                    _join_pages(item.get("source_pages", [])),
                    item.get("source_excerpt", ""),
                    item.get("review_status", ""),
                ]
            )

        for item in unit_package.get("dialogue_samples", []):
            dialogue_rows.append(
                [
                    textbook_name,
                    textbook_version,
                    unit_code,
                    unit_name,
                    item.get("title", ""),
                    len(item.get("turns", [])),
                    _join_pages(item.get("source_pages", [])),
                    item.get("source_excerpt", ""),
                    item.get("review_status", ""),
                ]
            )
            for turn in item.get("turns", []):
                dialogue_turn_rows.append(
                    [
                        textbook_name,
                        textbook_version,
                        unit_code,
                        unit_name,
                        item.get("title", ""),
                        turn.get("turn_index", ""),
                        turn.get("speaker", ""),
                        turn.get("text_en", ""),
                        turn.get("text_zh", ""),
                        item.get("review_status", ""),
                    ]
                )

        task_rows.append(
            [
                textbook_name,
                textbook_version,
                unit_code,
                unit_name,
                unit_package["unit_task"].get("task_intro", ""),
                _join(unit_package["unit_task"].get("source_basis", [])),
                unit_package["unit_task"].get("review_status", ""),
            ]
        )
        prompt_rows.append(
            [
                textbook_name,
                textbook_version,
                unit_code,
                unit_name,
                unit_package["unit_prompt"].get("unit_theme", ""),
                _join(unit_package["unit_prompt"].get("grammar_rules", [])),
                _join(unit_package["unit_prompt"].get("prompt_notes", [])),
                _join(unit_package["unit_prompt"].get("source_basis", [])),
                unit_package["unit_prompt"].get("review_status", ""),
            ]
        )

    total_vocabulary = len(vocabulary_rows) - 1
    total_patterns = len(sentence_rows) - 1
    total_dialogues = len(dialogue_rows) - 1

    book_rows = [[
        "教材名称",
        "教材版本",
        "出版社",
        "年级",
        "学期",
        "来源任务ID",
        "审核状态",
        "单元数量",
        "词汇数量",
        "句型数量",
        "对话数量",
        "审核记录数",
        "导出范围",
        "仅导出通过项",
        "导出时间",
    ], [
        textbook_name,
        textbook_version,
        book.get("publisher", ""),
        book.get("grade", ""),
        book.get("term", ""),
        book.get("source_job_id", ""),
        book.get("review_status", ""),
        len(units),
        total_vocabulary,
        total_patterns,
        total_dialogues,
        len(review_records),
        payload.get("export_meta", {}).get("export_scope", "book"),
        "是" if payload.get("export_meta", {}).get("approved_only") else "否",
        payload.get("export_meta", {}).get("exported_at", ""),
    ]]

    review_rows = [[
        "review_id",
        "target_type",
        "target_id",
        "review_status",
        "review_notes",
        "reviewer",
        "reviewed_at",
    ]]
    for record in review_records:
        review_rows.append(
            [
                record.get("review_id", ""),
                record.get("target_type", ""),
                record.get("target_id", ""),
                record.get("review_status", ""),
                record.get("review_notes", ""),
                record.get("reviewer", ""),
                record.get("reviewed_at", ""),
            ]
        )

    return [
        ("教材信息", book_rows),
        ("单元总表", unit_rows),
        ("词汇", vocabulary_rows),
        ("句型", sentence_rows),
        ("对话样例", dialogue_rows),
        ("对话轮次", dialogue_turn_rows),
        ("单元任务", task_rows),
        ("生成提示", prompt_rows),
        ("审核记录", review_rows),
    ]


def export_xlsx(payload: dict, output_path: Path) -> Path:
    sheets = _build_workbook_sheets(payload)
    used_names: set[str] = set()
    sheet_specs = [(_make_sheet_name(name, used_names), rows) for name, rows in sheets]

    workbook_xml = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">',
        "<sheets>",
    ]
    workbook_rels_xml = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">',
    ]
    content_types_xml = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
    ]

    sheet_xml_map: dict[str, str] = {}
    for index, (sheet_name, rows) in enumerate(sheet_specs, start=1):
        workbook_xml.append(f'<sheet name="{escape(sheet_name)}" sheetId="{index}" r:id="rId{index}"/>')
        workbook_rels_xml.append(
            '<Relationship '
            f'Id="rId{index}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{index}.xml"/>'
        )
        content_types_xml.append(
            '<Override '
            f'PartName="/xl/worksheets/sheet{index}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
        sheet_xml_map[f"xl/worksheets/sheet{index}.xml"] = _build_sheet_xml(rows)

    style_relation_id = len(sheet_specs) + 1
    workbook_xml.extend(["</sheets>", "</workbook>"])
    workbook_rels_xml.extend(
        [
            '<Relationship '
            f'Id="rId{style_relation_id}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
            'Target="styles.xml"/>',
            "</Relationships>",
        ]
    )
    content_types_xml.append("</Types>")

    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2">'
        '<font><sz val="11"/><name val="Calibri"/><family val="2"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/><family val="2"/></font>'
        "</fonts>"
        '<fills count="2">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        "</fills>"
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
        "</cellXfs>"
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        "</styleSheet>"
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            "".join(content_types_xml),
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/>'
            "</Relationships>",
        )
        archive.writestr("xl/workbook.xml", "".join(workbook_xml))
        archive.writestr("xl/_rels/workbook.xml.rels", "".join(workbook_rels_xml))
        archive.writestr("xl/styles.xml", styles_xml)
        for sheet_path, sheet_xml in sheet_xml_map.items():
            archive.writestr(sheet_path, sheet_xml)

    return output_path
