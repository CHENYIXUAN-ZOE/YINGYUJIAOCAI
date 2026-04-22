from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.schemas.content import Classification, UnitRecord
from app.services.generator.prompt_builder import build_unit_generation_prompt
from app.services.generator.unit_content_generator import UnitContentGenerator


def build_settings(tmp_path) -> Settings:
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
        allow_placeholder_fallback=False,
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
    assert "对话必须为 10-15 轮" in prompt
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
