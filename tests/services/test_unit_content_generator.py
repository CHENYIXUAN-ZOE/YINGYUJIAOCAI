from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.schemas.content import Classification, UnitRecord
from app.services.generator.prompt_builder import build_unit_generation_prompt
from app.services.generator.unit_content_generator import UnitContentGenerator


def build_settings(tmp_path, *, allow_placeholder_fallback: bool = False) -> Settings:
    settings = Settings(
        base_dir=tmp_path,
        data_dir=tmp_path / "data",
        upload_dir=tmp_path / "data" / "uploads",
        parsed_dir=tmp_path / "data" / "parsed",
        export_dir=tmp_path / "data" / "exports",
        job_dir=tmp_path / "data" / "parsed" / "jobs",
        result_dir=tmp_path / "data" / "parsed" / "results",
        review_dir=tmp_path / "data" / "parsed" / "reviews",
        web_dir=tmp_path / "app" / "web",
        template_dir=tmp_path / "app" / "web" / "templates",
        static_dir=tmp_path / "app" / "web" / "static",
        google_application_credentials=None,
        google_cloud_project=None,
        allow_placeholder_fallback=allow_placeholder_fallback,
    )
    settings.ensure_directories()
    return settings


def test_build_unit_package_requires_external_api_by_default(tmp_path):
    settings = build_settings(tmp_path)
    generator = UnitContentGenerator(settings)
    unit_record = UnitRecord(
        unit_id="job_demo_unit_1",
        classification=Classification(
            textbook_version="北师大版",
            textbook_name="北师大版英语 3A",
            unit_code="Unit 1",
            unit_name="Hello!",
        ),
    )
    raw_unit = {
        "unit_code": "Unit 1",
        "unit_name": "Hello!",
        "source_pages": [4, 5],
        "text": "Hello! What's your name?",
        "lines": ["Hello! What's your name?"],
    }

    with pytest.raises(AppError) as exc_info:
        generator.build_unit_package(unit_record, raw_unit)

    assert exc_info.value.code == "API_GENERATION_REQUIRED"


def test_build_unit_generation_prompt_contains_common_constraints():
    classification = Classification(
        textbook_version="北师大版",
        textbook_name="北师大版英语 3A",
        unit_code="Unit 1",
        unit_name="My Family",
    )
    raw_unit = {
        "unit_theme": "My Family",
        "source_pages": [4, 5],
        "lines": [
            "Who is he?",
            "He is my father.",
            "This is my family photo.",
        ],
    }

    prompt = build_unit_generation_prompt(
        classification,
        raw_unit,
        "Who is he? He is my father. This is my family photo.",
    )

    assert "只处理当前 classification 对应的单元" in prompt
    assert "不要输出解释、Markdown、代码块或额外字段" in prompt
    assert "证据充分时整理为 6-12 轮" in prompt
    assert "不要为了凑轮次重复台词" in prompt
    assert "不要把整句误写成说话人" in prompt
    assert "`grammar_rules` 输出 1-3 条" in prompt
    assert "目标 15-30 个中文字符" in prompt
    assert '"unit_name": "My Family"' in prompt
    assert "Who is he?" in prompt


def test_unit_content_generator_build_prompt_uses_common_prompt_builder(tmp_path):
    settings = build_settings(tmp_path)
    generator = UnitContentGenerator(settings)
    classification = Classification(
        textbook_version="北师大版",
        textbook_name="北师大版英语 3A",
        unit_code="Unit 1",
        unit_name="My Family",
    )
    raw_unit = {
        "unit_theme": "My Family",
        "source_pages": [4, 5],
        "lines": ["Who is he?", "He is my father."],
    }

    prompt = generator._build_prompt(classification, raw_unit, "Who is he? He is my father.")

    assert "通用生成原则" in prompt
    assert "板块约束" in prompt
    assert '"source_pages": [' in prompt


def test_build_unit_package_fallback_uses_real_extracted_content(tmp_path):
    settings = build_settings(tmp_path, allow_placeholder_fallback=True)
    generator = UnitContentGenerator(settings)
    unit_record = UnitRecord(
        unit_id="job_demo_unit_2",
        classification=Classification(
            textbook_version="北师大版",
            textbook_name="北师大版英语 3A",
            unit_code="Unit 2",
            unit_name="My School",
        ),
        unit_theme="My School",
        source_pages=[6, 7],
    )
    raw_unit = {
        "unit_code": "Unit 2",
        "unit_name": "My School",
        "unit_theme": "My School",
        "source_pages": [6, 7],
        "lines": [
            "Words",
            "school n. 学校",
            "classroom n. 教室",
            "Key Sentences",
            "Where is the library?",
            "This is our classroom.",
            "Listen and say",
            "A: Where is the library?",
            "B: It is next to the classroom.",
        ],
        "section_lines": {
            "vocabulary": ["school n. 学校", "classroom n. 教室"],
            "sentence_patterns": ["Where is the library?", "This is our classroom."],
            "dialogue_samples": ["A: Where is the library?", "B: It is next to the classroom."],
        },
    }

    package = generator.build_unit_package(unit_record, raw_unit)

    assert [item.word for item in package.vocabulary] == ["school", "classroom"]
    assert [item.pattern for item in package.sentence_patterns] == [
        "Where is the library?",
        "This is our classroom.",
    ]
    assert package.dialogue_samples[0].turns[0].text_en == "Where is the library?"
    assert "My School" in package.unit_task.task_intro
    assert package.unit_prompt.unit_theme == "My School"
    assert any("school" in basis.lower() for basis in package.unit_prompt.source_basis)


def test_build_unit_package_recovers_from_schema_mismatch_with_rule_fallback(tmp_path, monkeypatch):
    settings = build_settings(tmp_path, allow_placeholder_fallback=False)
    generator = UnitContentGenerator(settings)
    unit_record = UnitRecord(
        unit_id="job_demo_unit_2",
        classification=Classification(
            textbook_version="北师大版",
            textbook_name="北师大版英语 3A",
            unit_code="Unit 2",
            unit_name="My School",
        ),
        unit_theme="My School",
        source_pages=[6, 7],
    )
    raw_unit = {
        "unit_code": "Unit 2",
        "unit_name": "My School",
        "unit_theme": "My School",
        "source_pages": [6, 7],
        "lines": [
            "Words",
            "school n. 学校",
            "classroom n. 教室",
            "Key Sentences",
            "Where is the library?",
            "This is our classroom.",
            "Listen and say",
            "A: Where is the library?",
            "B: It is next to the classroom.",
        ],
        "section_lines": {
            "vocabulary": ["school n. 学校", "classroom n. 教室"],
            "sentence_patterns": ["Where is the library?", "This is our classroom."],
            "dialogue_samples": ["A: Where is the library?", "B: It is next to the classroom."],
        },
    }

    monkeypatch.setattr(generator, "_vertex_ai_ready", lambda: True)

    def fail_vertex(*_args, **_kwargs):
        raise AppError("GEMINI_SCHEMA_MISMATCH", "Gemini returned an unexpected schema", status_code=502)

    monkeypatch.setattr(generator, "_build_with_vertex_ai", fail_vertex)

    package = generator.build_unit_package(unit_record, raw_unit)

    assert [item.word for item in package.vocabulary] == ["school", "classroom"]
    assert package.dialogue_samples[0].turns[0].text_en == "Where is the library?"


def test_repair_model_payload_salvages_loose_sections_before_validation(tmp_path):
    settings = build_settings(tmp_path)
    generator = UnitContentGenerator(settings)
    unit_record = UnitRecord(
        unit_id="job_demo_unit_4",
        classification=Classification(
            textbook_version="北师大版",
            textbook_name="北师大版英语 4B",
            unit_code="Unit 3",
            unit_name="Fruits",
        ),
        unit_theme="Fruits",
        source_pages=[8, 9],
    )
    raw_unit = {
        "unit_code": "Unit 3",
        "unit_name": "Fruits",
        "unit_theme": "Fruits",
        "source_pages": [8, 9],
        "lines": [
            "Words",
            "apple n. 苹果",
            "pear n. 梨",
            "Key Sentences",
            "Do you like apples?",
            "Yes, I do.",
            "Listen and say",
            "A: Do you like apples?",
            "B: Yes, I do.",
        ],
        "section_lines": {
            "vocabulary": ["apple n. 苹果", "pear n. 梨"],
            "sentence_patterns": ["Do you like apples?", "Yes, I do."],
            "dialogue_samples": ["A: Do you like apples?", "B: Yes, I do."],
        },
    }
    payload = {
        "unit_theme": " Fruits ",
        "vocabulary": ["apple"],
        "sentence_patterns": [{"text": "Do you like apples?", "example_sentences": "Yes, I do."}],
        "dialogue_samples": ["A: Do you like apples?\nB: Yes, I do."],
        "unit_task": "Talk about fruits",
        "unit_prompt": {"theme": "Fruits", "rules": "Do you like apples?"},
    }

    repaired = generator._repair_model_payload(unit_record, raw_unit, payload)
    package = generator._payload_to_unit_package(unit_record, [8, 9], repaired)

    assert package.vocabulary[0].word == "apple"
    assert package.sentence_patterns[0].pattern == "Do you like apples?"
    assert package.dialogue_samples[0].turns[0].speaker == "A"
    assert package.unit_task.task_intro == "Talk about fruits"
    assert package.unit_prompt.unit_theme == "Fruits"


def test_payload_to_unit_package_normalizes_dialogue_turns(tmp_path):
    settings = build_settings(tmp_path)
    generator = UnitContentGenerator(settings)
    unit_record = UnitRecord(
        unit_id="job_demo_unit_3",
        classification=Classification(
            textbook_version="北师大版",
            textbook_name="北师大版英语 3B",
            unit_code="Unit 7",
            unit_name="Fruits",
        ),
        unit_theme="Fruits",
        source_pages=[4, 5],
    )

    payload = {
        "unit_theme": " Fruits ",
        "vocabulary": [
            {
                "word": " banana ",
                "part_of_speech": " n. ",
                "meaning_zh": " 香蕉 ",
                "example_sentences": [" It is a banana. "],
                "source_excerpt": " Lesson 1 \n It's a banana. ",
            }
        ],
        "sentence_patterns": [
            {
                "pattern": " Can you ...? ",
                "usage_note": " 能力问答 ",
                "examples": [" Can you jump? "],
                "source_excerpt": " Can you jump? ",
            }
        ],
        "dialogue_samples": [
            {
                "title": " Story Time ",
                "source_excerpt": " A: Hello.\nB: Hi. ",
                "turns": [
                    {"speaker": " A ", "text_en": " Hello. ", "text_zh": " 你好。 "},
                    {"speaker": " A ", "text_en": " Hello. ", "text_zh": " 你好。 "},
                    {"speaker": " B ", "text_en": " Hi. ", "text_zh": " 嗨。 "},
                    {"speaker": " C ", "text_en": f"Turn {3}", "text_zh": "第三句"},
                    {"speaker": " C ", "text_en": f"Turn {4}", "text_zh": "第四句"},
                    {"speaker": " C ", "text_en": f"Turn {5}", "text_zh": "第五句"},
                    {"speaker": " C ", "text_en": f"Turn {6}", "text_zh": "第六句"},
                    {"speaker": " C ", "text_en": f"Turn {7}", "text_zh": "第七句"},
                    {"speaker": " C ", "text_en": f"Turn {8}", "text_zh": "第八句"},
                    {"speaker": " C ", "text_en": f"Turn {9}", "text_zh": "第九句"},
                    {"speaker": " C ", "text_en": f"Turn {10}", "text_zh": "第十句"},
                    {"speaker": " C ", "text_en": f"Turn {11}", "text_zh": "第十一句"},
                    {"speaker": " C ", "text_en": f"Turn {12}", "text_zh": "第十二句"},
                    {"speaker": " C ", "text_en": f"Turn {13}", "text_zh": "第十三句"},
                ],
            }
        ],
        "unit_task": {
            "task_intro": " 认识水果并进行问答 ",
            "source_basis": [" Fruits ", " Can you...? "],
        },
        "unit_prompt": {
            "unit_theme": " Fruits ",
            "grammar_rules": [" It is ... "],
            "prompt_notes": [" Keep it short. "],
            "source_basis": [" Story Time "],
        },
    }

    package = generator._payload_to_unit_package(unit_record, [4, 5], payload)

    assert package.unit.unit_theme == "Fruits"
    assert package.vocabulary[0].word == "banana"
    assert package.vocabulary[0].source_excerpt == "Lesson 1 It's a banana."
    assert package.dialogue_samples[0].title == "Story Time"
    assert package.dialogue_samples[0].source_excerpt == "A: Hello. B: Hi."
    assert len(package.dialogue_samples[0].turns) == 12
    assert package.dialogue_samples[0].turns[0].speaker == "A"
    assert package.dialogue_samples[0].turns[1].speaker == "B"
    assert package.dialogue_samples[0].turns[1].text_en == "Hi."
    assert package.unit_task.task_intro == "认识水果并进行问答"
