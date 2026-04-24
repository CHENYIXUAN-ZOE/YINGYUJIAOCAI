from __future__ import annotations

from concurrent.futures import Executor, Future
import zipfile

import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.repositories.export_repo import ExportRepository
from app.repositories.job_repo import JobRepository
from app.repositories.result_repo import ResultRepository
from app.repositories.review_repo import ReviewRepository
from app.schemas.content import (
    Classification,
    DialogueSample,
    DialogueTurn,
    SentencePattern,
    UnitPackage,
    UnitPrompt,
    UnitRecord,
    UnitTask,
    VocabularyItem,
)
from app.schemas.common import ParseStatus
from app.schemas.export import ExportRequest
from app.services.job_service import JobService


def build_settings(tmp_path) -> Settings:
    data_dir = tmp_path / "data"
    parsed_dir = data_dir / "parsed"
    export_dir = data_dir / "exports"
    web_dir = tmp_path / "app" / "web"
    settings = Settings(
        base_dir=tmp_path,
        data_dir=data_dir,
        upload_dir=data_dir / "uploads",
        parsed_dir=parsed_dir,
        export_dir=export_dir,
        job_dir=parsed_dir / "jobs",
        result_dir=parsed_dir / "results",
        review_dir=parsed_dir / "reviews",
        web_dir=web_dir,
        template_dir=web_dir / "templates",
        static_dir=web_dir / "static",
    )
    settings.ensure_directories()
    return settings


class StubUnitContentGenerator:
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail

    def build_unit_package(self, unit_record: UnitRecord, raw_unit: dict) -> UnitPackage:
        if self.should_fail:
            raise AppError("GEMINI_REQUEST_FAILED", "boom", status_code=502)
        classification: Classification = unit_record.classification
        unit_id = unit_record.unit_id
        return UnitPackage(
            unit=unit_record,
            vocabulary=[
                VocabularyItem(
                    item_id=f"{unit_id}_voc_1",
                    classification=classification,
                    word="family",
                    part_of_speech="n.",
                    meaning_zh="家庭",
                    example_sentences=["This is my family."],
                    source_pages=[1],
                    source_excerpt="family",
                )
            ],
            sentence_patterns=[
                SentencePattern(
                    item_id=f"{unit_id}_sp_1",
                    classification=classification,
                    pattern="Who is he?",
                    usage_note="询问人物身份",
                    examples=["Who is he?"],
                    source_pages=[1],
                    source_excerpt="Who is he?",
                )
            ],
            dialogue_samples=[
                DialogueSample(
                    item_id=f"{unit_id}_dlg_1",
                    classification=classification,
                    title="Family Talk",
                    turns=[
                        DialogueTurn(
                            turn_index=1,
                            speaker="A",
                            text_en="Who is he?",
                            text_zh="他是谁？",
                        ),
                        DialogueTurn(
                            turn_index=2,
                            speaker="B",
                            text_en="He is my father.",
                            text_zh="他是我的爸爸。",
                        ),
                    ],
                    source_pages=[1],
                    source_excerpt="Who is he?",
                )
            ],
            unit_task=UnitTask(
                item_id=f"{unit_id}_task_1",
                classification=classification,
                task_intro="介绍家庭成员",
                source_basis=["family", "Who is he?"],
            ),
            unit_prompt=UnitPrompt(
                item_id=f"{unit_id}_prompt_1",
                classification=classification,
                unit_theme="My Family",
                grammar_rules=["Use He is my ..."],
                prompt_notes=["Keep sentences short."],
                source_basis=["family dialogue"],
            ),
        )


class ImmediateExecutor(Executor):
    def submit(self, fn, /, *args, **kwargs):
        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:  # pragma: no cover - delegated to assertions
            future.set_exception(exc)
        return future


def build_service(settings: Settings, generator: StubUnitContentGenerator) -> JobService:
    return JobService(
        upload_dir=settings.upload_dir,
        export_dir=settings.export_dir,
        job_repo=JobRepository(settings),
        result_repo=ResultRepository(settings),
        review_repo=ReviewRepository(settings),
        export_repo=ExportRepository(settings),
        unit_content_generator=generator,
        executor=ImmediateExecutor(),
    )


def patch_parse_pipeline(monkeypatch):
    monkeypatch.setattr("app.services.job_service.pdf_loader.load_pdf", lambda _: {"stem": "sample", "lines": []})
    monkeypatch.setattr("app.services.job_service.ocr_processor.process", lambda doc, progress_callback=None: doc)
    monkeypatch.setattr("app.services.job_service.layout_analyzer.analyze", lambda doc: doc)
    monkeypatch.setattr(
        "app.services.job_service.unit_detector.detect",
        lambda doc: [
            {
                "unit_code": "Unit 1",
                "unit_name": "My Family",
                "unit_theme": "My Family",
                "source_pages": [1],
                "text": "Who is he? He is my father.",
            }
        ],
    )
    monkeypatch.setattr("app.services.job_service.section_classifier.classify", lambda doc, units: units)


def test_start_parse_persists_generated_result(tmp_path, monkeypatch):
    settings = build_settings(tmp_path)
    patch_parse_pipeline(monkeypatch)
    service = build_service(settings, StubUnitContentGenerator())

    job = service.create_job("sample.pdf", b"%PDF-1.4")
    updated = service.start_parse(job.job_id)

    assert updated.status == ParseStatus.reviewing
    payload = service.get_result(job.job_id)
    assert payload["units"][0]["unit"]["classification"]["unit_name"] == "My Family"
    assert payload["units"][0]["vocabulary"][0]["word"] == "family"
    status = service.get_job_status(job.job_id)
    assert status.status_label == "待审核"
    assert status.phase_label == "结果已生成"
    assert status.unit_total == 1
    assert status.unit_done == 1


def test_queue_parse_returns_queued_job_and_finishes_in_background(tmp_path, monkeypatch):
    settings = build_settings(tmp_path)
    patch_parse_pipeline(monkeypatch)
    service = build_service(settings, StubUnitContentGenerator())

    job = service.create_job("sample.pdf", b"%PDF-1.4")
    queued_job = service.queue_parse(job.job_id)

    assert queued_job.status == ParseStatus.queued
    assert queued_job.phase == "queued"

    finished_job = service.get_job(job.job_id)
    assert finished_job.status == ParseStatus.reviewing
    assert finished_job.phase == "review_ready"
    assert finished_job.started_at is not None
    assert finished_job.updated_at is not None


def test_get_result_rejects_job_before_parse_finishes(tmp_path):
    settings = build_settings(tmp_path)
    service = build_service(settings, StubUnitContentGenerator())

    job = service.create_job("sample.pdf", b"%PDF-1.4")

    with pytest.raises(AppError) as exc_info:
        service.get_result(job.job_id)

    assert exc_info.value.code == "PARSE_NOT_READY"


def test_start_parse_marks_job_failed_when_generation_errors(tmp_path, monkeypatch):
    settings = build_settings(tmp_path)
    patch_parse_pipeline(monkeypatch)
    service = build_service(settings, StubUnitContentGenerator(should_fail=True))

    job = service.create_job("sample.pdf", b"%PDF-1.4")

    with pytest.raises(AppError):
        service.start_parse(job.job_id)

    failed_job = service.get_job(job.job_id)
    assert failed_job.status == ParseStatus.failed
    assert "boom" in (failed_job.error_message or "")


def test_export_result_writes_xlsx_workbook(tmp_path, monkeypatch):
    settings = build_settings(tmp_path)
    patch_parse_pipeline(monkeypatch)
    service = build_service(settings, StubUnitContentGenerator())

    job = service.create_job("sample.pdf", b"%PDF-1.4")
    service.start_parse(job.job_id)

    metadata = service.export_result(
        ExportRequest(job_id=job.job_id, format="xlsx", approved_only=False),
    )

    assert metadata["format"] == "xlsx"
    workbook_path = settings.export_dir / f"{metadata['export_id']}.xlsx"
    assert workbook_path.exists()

    with zipfile.ZipFile(workbook_path) as archive:
        workbook_xml = archive.read("xl/workbook.xml").decode("utf-8")
        vocabulary_xml = archive.read("xl/worksheets/sheet3.xml").decode("utf-8")

    assert "词汇" in workbook_xml
    assert "教材名称" in vocabulary_xml
    assert "family" in vocabulary_xml


def test_delete_job_removes_related_files(tmp_path, monkeypatch):
    settings = build_settings(tmp_path)
    patch_parse_pipeline(monkeypatch)
    service = build_service(settings, StubUnitContentGenerator())

    job = service.create_job("sample.pdf", b"%PDF-1.4")
    service.start_parse(job.job_id)
    metadata = service.export_result(
        ExportRequest(job_id=job.job_id, format="json", approved_only=False),
    )

    assert (settings.job_dir / f"{job.job_id}.json").exists()
    assert (settings.result_dir / f"{job.job_id}.json").exists()
    assert (settings.review_dir / f"{job.job_id}.json").exists()
    assert (settings.export_dir / f"{metadata['export_id']}.meta.json").exists()
    assert (settings.export_dir / f"{metadata['export_id']}.json").exists()
    assert (settings.upload_dir / f"{job.job_id}_sample.pdf").exists()

    response = service.delete_job(job.job_id)

    assert response == {"job_id": job.job_id, "deleted": True}
    assert service.job_repo.get(job.job_id) is None
    assert service.result_repo.get(job.job_id) is None
    assert service.review_repo.get(job.job_id) == []
    assert not (settings.export_dir / f"{metadata['export_id']}.meta.json").exists()
    assert not (settings.export_dir / f"{metadata['export_id']}.json").exists()
    assert not (settings.upload_dir / f"{job.job_id}_sample.pdf").exists()


def test_delete_job_rejects_processing_task(tmp_path):
    settings = build_settings(tmp_path)
    service = build_service(settings, StubUnitContentGenerator())

    job = service.create_job("sample.pdf", b"%PDF-1.4")
    job.status = ParseStatus.queued
    service.job_repo.save(job)

    with pytest.raises(AppError) as exc_info:
        service.delete_job(job.job_id)

    assert exc_info.value.code == "JOB_BUSY"


def test_force_reparse_from_reviewing_increments_retry_count(tmp_path, monkeypatch):
    settings = build_settings(tmp_path)
    patch_parse_pipeline(monkeypatch)
    service = build_service(settings, StubUnitContentGenerator())

    job = service.create_job("sample.pdf", b"%PDF-1.4")
    service.start_parse(job.job_id)

    reparsed_job = service.queue_parse(job.job_id, force_reparse=True)

    assert reparsed_job.retry_count == 1
    finished_job = service.get_job(job.job_id)
    assert finished_job.status == ParseStatus.reviewing
    assert finished_job.retry_count == 1
