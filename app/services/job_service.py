from __future__ import annotations

from concurrent.futures import Executor, Future, ThreadPoolExecutor
import contextlib
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import threading
from uuid import uuid4

from app.core.config import get_settings
from app.core.errors import AppError
from app.repositories.export_repo import ExportRepository
from app.repositories.job_repo import JobRepository
from app.repositories.result_repo import ResultRepository
from app.repositories.review_repo import ReviewRepository
from app.schemas.common import GenerationMode, ParseStatus, ReviewStatus
from app.schemas.content import Book, Classification, ExportMeta, StructuredContent, UnitPackage, UnitRecord
from app.schemas.export import ExportRequest
from app.schemas.job import JobStatusResponse, ParseJob
from app.services.exporter.json_exporter import export_json
from app.services.exporter.markdown_exporter import export_markdown
from app.services.exporter.xlsx_exporter import export_xlsx
from app.services.generator.unit_content_generator import UnitContentGenerator
from app.services.parser import (
    layout_analyzer,
    ocr_processor,
    pdf_preflight,
    pdf_loader,
    section_classifier,
    unit_detector,
)

PARSE_STATUS_LABELS = {
    ParseStatus.uploaded.value: "已上传",
    ParseStatus.queued.value: "排队中",
    ParseStatus.parsing.value: "解析中",
    ParseStatus.structuring.value: "结构化中",
    ParseStatus.generating.value: "生成中",
    ParseStatus.reviewing.value: "待审核",
    ParseStatus.completed.value: "已完成",
    ParseStatus.failed.value: "失败",
}

REVIEW_STATE_LABELS = {
    "not_ready": "结果未生成",
    "pending_review": "审核进行中",
    "needs_revision": "存在返修",
    "has_rejections": "存在驳回",
    "approved": "全部通过",
}

PHASE_LABELS = {
    "uploaded": "等待开始",
    "queued": "等待后台任务",
    "loading_pdf": "加载 PDF",
    "extracting_text": "读取文字层",
    "running_ocr": "执行 OCR",
    "analyzing_layout": "分析页面结构",
    "detecting_units": "识别单元边界",
    "classifying_sections": "整理单元板块",
    "generating_units": "生成单元内容",
    "saving_results": "保存结果",
    "review_ready": "结果已生成",
    "failed": "处理失败",
}

PROCESSING_STATUSES = {
    ParseStatus.queued,
    ParseStatus.parsing,
    ParseStatus.structuring,
    ParseStatus.generating,
}

_UNSET = object()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobService:
    def __init__(
        self,
        upload_dir: Path,
        export_dir: Path,
        job_repo: JobRepository,
        result_repo: ResultRepository,
        review_repo: ReviewRepository,
        export_repo: ExportRepository,
        unit_content_generator: UnitContentGenerator | None = None,
        executor: Executor | None = None,
    ):
        self.upload_dir = upload_dir
        self.export_dir = export_dir
        self.job_repo = job_repo
        self.result_repo = result_repo
        self.review_repo = review_repo
        self.export_repo = export_repo
        self.unit_content_generator = unit_content_generator or UnitContentGenerator(get_settings())
        self._executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="parse-worker")
        self._active_jobs: dict[str, Future] = {}
        self._lock = threading.RLock()

    def create_job(self, file_name: str, content: bytes) -> ParseJob:
        job_id = f"job_{uuid4().hex[:10]}"
        file_path = self.upload_dir / f"{job_id}_{file_name}"
        file_path.write_bytes(content)
        created_at = _now_iso()
        preflight = pdf_preflight.analyze_pdf(file_path)
        job = ParseJob(
            job_id=job_id,
            file_name=file_name,
            file_path=str(file_path),
            status=ParseStatus.uploaded,
            progress=0,
            phase="uploaded",
            phase_message="任务已创建，等待启动解析。",
            created_at=created_at,
            updated_at=created_at,
            review_status=ReviewStatus.pending,
            preflight=preflight,
        )
        return self.job_repo.save(job)

    def get_job(self, job_id: str) -> ParseJob:
        job = self.job_repo.get(job_id)
        if not job:
            raise AppError("JOB_NOT_FOUND", "job_id does not exist", status_code=404)
        return job

    def get_job_status(self, job_id: str) -> JobStatusResponse:
        job = self.get_job(job_id)
        return self._to_job_status(job)

    def delete_job(self, job_id: str) -> dict:
        job = self.get_job(job_id)
        if job.status in PROCESSING_STATUSES:
            raise AppError(
                "JOB_BUSY",
                "job is currently processing",
                status_code=409,
                details={"job_id": job.job_id, "status": job.status.value, "phase": job.phase},
                retryable=True,
                phase=job.phase,
            )

        self.result_repo.delete(job_id)
        self.review_repo.delete(job_id)
        self.export_repo.delete_exports_for_job(job_id)
        self.job_repo.delete(job_id)
        with contextlib.suppress(FileNotFoundError):
            Path(job.file_path).unlink()
        return {"job_id": job_id, "deleted": True}

    def queue_parse(self, job_id: str, force_reparse: bool = False) -> ParseJob:
        job = self._prepare_job_for_parse(job_id, force_reparse=force_reparse, queued=True)
        with self._lock:
            future = self._executor.submit(self._run_parse_pipeline, job.job_id)
            self._active_jobs[job.job_id] = future
        future.add_done_callback(lambda _future, active_job_id=job.job_id: self._clear_active_job(active_job_id))
        return job

    def start_parse(self, job_id: str, force_reparse: bool = False) -> ParseJob:
        self._prepare_job_for_parse(job_id, force_reparse=force_reparse, queued=False)
        return self._run_parse_pipeline(job_id)

    def recover_incomplete_jobs(self) -> list[ParseJob]:
        recovered_jobs: list[ParseJob] = []
        for job in self.job_repo.list():
            if job.status not in PROCESSING_STATUSES:
                continue
            with self._lock:
                active_future = self._active_jobs.get(job.job_id)
                if active_future and not active_future.done():
                    continue
            self.review_repo.delete(job.job_id)
            recovered_jobs.append(
                self._set_job_state(
                    job,
                    status=ParseStatus.failed,
                    phase="failed",
                    phase_message="检测到上次处理在中途结束，任务已恢复为可重试状态。",
                    error_message="上次处理因服务重启或异常中断而未完成，请重新解析。",
                    last_error_code="JOB_RECOVERED_AFTER_RESTART",
                    retryable=True,
                    finished_at=_now_iso(),
                )
            )
        return recovered_jobs

    def _prepare_job_for_parse(self, job_id: str, force_reparse: bool, queued: bool) -> ParseJob:
        with self._lock:
            active_future = self._active_jobs.get(job_id)
            if active_future and not active_future.done():
                raise AppError(
                    "INVALID_REQUEST",
                    "job is already processing",
                    status_code=400,
                    details={"job_id": job_id},
                    retryable=True,
                )

        job = self.get_job(job_id)
        initial_statuses = {ParseStatus.uploaded, ParseStatus.failed}
        reparsable_statuses = initial_statuses | {ParseStatus.reviewing, ParseStatus.completed}
        allowed_statuses = reparsable_statuses if force_reparse else initial_statuses
        if job.status not in allowed_statuses:
            raise AppError(
                "INVALID_REQUEST",
                "job cannot be started in its current state",
                status_code=400,
                details={
                    "job_id": job.job_id,
                    "status": job.status.value,
                    "phase": job.phase,
                    "force_reparse": force_reparse,
                },
                retryable=job.status in reparsable_statuses,
                phase=job.phase,
            )

        preserve_partial_result = job.status == ParseStatus.failed and not force_reparse
        if not preserve_partial_result:
            self.result_repo.delete(job_id)
        self.review_repo.delete(job_id)

        retry_count = job.retry_count
        if job.status != ParseStatus.uploaded:
            retry_count += 1

        return self._set_job_state(
            job,
            status=ParseStatus.queued if queued else ParseStatus.parsing,
            progress=0 if queued else 5,
            phase="queued" if queued else "loading_pdf",
            phase_message="任务已进入后台队列，等待处理。" if queued else "正在加载教材 PDF。",
            page_total=0,
            page_done=0,
            unit_total=0,
            unit_done=0,
            retry_count=retry_count,
            error_message=None,
            last_error_code=None,
            retryable=False,
            review_status=ReviewStatus.pending,
            started_at=None if queued else _now_iso(),
            finished_at=None,
        )

    def _run_parse_pipeline(self, job_id: str) -> ParseJob:
        job = self.get_job(job_id)
        try:
            if job.status == ParseStatus.queued:
                job = self._set_job_state(
                    job,
                    status=ParseStatus.parsing,
                    progress=5,
                    phase="loading_pdf",
                    phase_message="正在加载教材 PDF。",
                    started_at=_now_iso(),
                )

            def update_ocr_progress(processed_pages: int, total_pages: int) -> None:
                if total_pages <= 0:
                    return
                next_progress = min(40, 10 + int(30 * processed_pages / total_pages))
                self._set_job_state(
                    job,
                    status=ParseStatus.parsing,
                    progress=next_progress,
                    phase="running_ocr",
                    phase_message=f"正在处理第 {processed_pages}/{total_pages} 页。",
                    page_total=total_pages,
                    page_done=processed_pages,
                )

            document = pdf_loader.load_pdf(Path(job.file_path))
            initial_page_total = self._estimate_page_total(document)
            job = self._set_job_state(
                job,
                status=ParseStatus.parsing,
                progress=max(job.progress, 10),
                phase="extracting_text",
                phase_message="正在读取文字层并准备 OCR。",
                page_total=initial_page_total,
                page_done=0,
            )
            document = ocr_processor.process(document, progress_callback=update_ocr_progress)
            page_total = max(initial_page_total, self._estimate_page_total(document))
            text_message = "已完成 OCR 文本提取。" if document.get("ocr_used") else "已直接使用 PDF 文字层。"
            job = self._set_job_state(
                job,
                status=ParseStatus.parsing,
                progress=max(job.progress, 40),
                phase="running_ocr" if document.get("ocr_used") else "extracting_text",
                phase_message=text_message,
                page_total=page_total,
                page_done=page_total,
            )

            job = self._set_job_state(
                job,
                status=ParseStatus.structuring,
                progress=45,
                phase="analyzing_layout",
                phase_message="正在分析页面结构。",
            )
            document = layout_analyzer.analyze(document)

            job = self._set_job_state(
                job,
                status=ParseStatus.structuring,
                progress=50,
                phase="detecting_units",
                phase_message="正在识别单元边界。",
            )
            units = unit_detector.detect(document)

            job = self._set_job_state(
                job,
                status=ParseStatus.structuring,
                progress=55,
                phase="classifying_sections",
                phase_message="正在整理单元板块。",
                unit_total=len(units),
                unit_done=0,
            )
            units = section_classifier.classify(document, units)

            def update_generation_progress(processed_units: int, total_units: int) -> None:
                if total_units <= 0:
                    return
                next_progress = min(95, 60 + int(35 * processed_units / total_units))
                self._set_job_state(
                    job,
                    status=ParseStatus.generating,
                    progress=next_progress,
                    phase="generating_units",
                    phase_message=f"正在生成第 {processed_units}/{total_units} 个单元。",
                    unit_total=total_units,
                    unit_done=processed_units,
                )

            partial_result, completed_units = self._prepare_incremental_result(job, units)

            job = self._set_job_state(
                job,
                status=ParseStatus.generating,
                progress=min(95, 60 + int(35 * completed_units / len(units))) if units else 60,
                phase="generating_units",
                phase_message=f"正在生成 {len(units)} 个单元的结构化内容。",
                unit_total=len(units),
                unit_done=completed_units,
            )

            result = self._build_result(
                job,
                document,
                units,
                generation_progress_callback=update_generation_progress,
                existing_payload=partial_result,
                completed_units=completed_units,
            )
            job = self._set_job_state(
                job,
                status=ParseStatus.generating,
                progress=98,
                phase="saving_results",
                phase_message="正在保存结果与审核记录。",
                unit_total=len(units),
                unit_done=len(units),
            )
            self.result_repo.save(job_id, result)
            self.review_repo.save(job_id, result["review_records"])

            job = self._set_job_state(
                job,
                status=ParseStatus.reviewing,
                progress=100,
                phase="review_ready",
                phase_message="结果已生成，可以进入审核。",
                finished_at=_now_iso(),
            )

            result["job"] = job.model_dump(mode="json")
            self.result_repo.save(job_id, result)
            return job
        except Exception as exc:
            error_code = exc.code if isinstance(exc, AppError) else "UNEXPECTED_ERROR"
            error_message = exc.message if isinstance(exc, AppError) else str(exc)
            retryable = exc.retryable if isinstance(exc, AppError) else True
            self._set_job_state(
                job,
                status=ParseStatus.failed,
                phase="failed",
                phase_message="处理失败，请查看错误信息后重试。",
                error_message=error_message,
                last_error_code=error_code,
                retryable=retryable,
                finished_at=_now_iso(),
            )
            raise

    def _build_result(
        self,
        job: ParseJob,
        document: dict,
        units: list[dict],
        generation_progress_callback=None,
        existing_payload: dict | None = None,
        completed_units: int = 0,
    ) -> dict:
        payload = existing_payload or self._initialize_result_payload(job, units)
        unit_packages = payload.setdefault("units", [])
        for index, raw_unit in enumerate(units[completed_units:], start=completed_units + 1):
            unit_record = self._build_unit_record(job, raw_unit, index)
            unit_package = self.unit_content_generator.build_unit_package(unit_record, raw_unit)
            unit_packages.append(unit_package.model_dump(mode="json"))
            payload["job"] = job.model_dump(mode="json")
            payload["export_meta"] = ExportMeta(
                schema_version="v1",
                export_scope="book",
                approved_only=True,
                unit_ids=[package["unit"]["unit_id"] for package in unit_packages],
            ).model_dump(mode="json")
            self.result_repo.save(job.job_id, payload)
            if generation_progress_callback:
                generation_progress_callback(index, len(units))
        return payload

    def _estimate_page_total(self, document: dict) -> int:
        page_texts = document.get("page_texts") or []
        if page_texts:
            return len(page_texts)
        page_lines = document.get("page_lines") or []
        if page_lines:
            return max(int(item.get("page_num", 1)) for item in page_lines)
        return 0

    def _initialize_result_payload(self, job: ParseJob, units: list[dict]) -> dict:
        textbook_version = self._infer_textbook_version(job.file_name)
        textbook_name = Path(job.file_name).stem
        payload = StructuredContent(
            job=job.model_dump(mode="json"),
            book=Book(
                book_id=f"book_{job.job_id}",
                textbook_version=textbook_version,
                textbook_name=textbook_name,
                publisher=textbook_version,
                source_job_id=job.job_id,
                source_pages=[1],
                confidence=0.5,
                review_status=ReviewStatus.pending,
            ),
            units=[],
            review_records=[],
            export_meta=ExportMeta(
                schema_version="v1",
                export_scope="book",
                approved_only=True,
                unit_ids=[f"{job.job_id}_unit_{index}" for index in range(1, len(units) + 1)],
            ),
        )
        return payload.model_dump(mode="json")

    def _build_unit_record(self, job: ParseJob, raw_unit: dict, index: int) -> UnitRecord:
        textbook_version = self._infer_textbook_version(job.file_name)
        textbook_name = Path(job.file_name).stem
        classification = Classification(
            textbook_version=textbook_version,
            textbook_name=textbook_name,
            unit_code=raw_unit["unit_code"],
            unit_name=raw_unit["unit_name"],
        )
        return UnitRecord(
            unit_id=f"{job.job_id}_unit_{index}",
            classification=classification,
            unit_theme=raw_unit.get("unit_theme"),
            source_pages=raw_unit.get("source_pages", [1]),
            confidence=0.5,
            review_status=ReviewStatus.pending,
        )

    def _prepare_incremental_result(self, job: ParseJob, units: list[dict]) -> tuple[dict, int]:
        payload = self.result_repo.get(job.job_id)
        if not payload:
            payload = self._initialize_result_payload(job, units)
            self.result_repo.save(job.job_id, payload)
            return payload, 0

        if not self._is_reusable_partial_result(job, payload, units):
            payload = self._initialize_result_payload(job, units)
            self.result_repo.save(job.job_id, payload)
            return payload, 0

        payload["job"] = job.model_dump(mode="json")
        payload["review_records"] = []
        self.result_repo.save(job.job_id, payload)
        return payload, len(payload.get("units") or [])

    def _is_reusable_partial_result(self, job: ParseJob, payload: dict, units: list[dict]) -> bool:
        if payload.get("job", {}).get("job_id") != job.job_id:
            return False
        existing_units = payload.get("units") or []
        if len(existing_units) > len(units):
            return False
        for index, unit_package in enumerate(existing_units, start=1):
            unit_record = unit_package.get("unit") or {}
            raw_unit = units[index - 1]
            if unit_record.get("unit_id") != f"{job.job_id}_unit_{index}":
                return False
            classification = unit_record.get("classification") or {}
            if classification.get("unit_code") != raw_unit.get("unit_code"):
                return False
            if classification.get("unit_name") != raw_unit.get("unit_name"):
                return False
        return True

    def _set_job_state(
        self,
        job: ParseJob,
        *,
        status=_UNSET,
        progress=_UNSET,
        phase=_UNSET,
        phase_message=_UNSET,
        page_total=_UNSET,
        page_done=_UNSET,
        unit_total=_UNSET,
        unit_done=_UNSET,
        retry_count=_UNSET,
        error_message=_UNSET,
        last_error_code=_UNSET,
        retryable=_UNSET,
        review_status=_UNSET,
        started_at=_UNSET,
        finished_at=_UNSET,
    ) -> ParseJob:
        if status is not _UNSET:
            job.status = status
        if progress is not _UNSET:
            job.progress = max(0, min(100, int(progress)))
        if phase is not _UNSET:
            job.phase = str(phase)
        if phase_message is not _UNSET:
            job.phase_message = phase_message
        if page_total is not _UNSET:
            job.page_total = max(0, int(page_total))
        if page_done is not _UNSET:
            job.page_done = max(0, int(page_done))
        if unit_total is not _UNSET:
            job.unit_total = max(0, int(unit_total))
        if unit_done is not _UNSET:
            job.unit_done = max(0, int(unit_done))
        if retry_count is not _UNSET:
            job.retry_count = max(0, int(retry_count))
        if error_message is not _UNSET:
            job.error_message = error_message
        if last_error_code is not _UNSET:
            job.last_error_code = last_error_code
        if retryable is not _UNSET:
            job.retryable = bool(retryable)
        if review_status is not _UNSET:
            job.review_status = review_status
        if started_at is not _UNSET:
            job.started_at = started_at
        if finished_at is not _UNSET:
            job.finished_at = finished_at
        job.updated_at = _now_iso()
        self.job_repo.save(job)
        return job

    def _to_job_status(self, job: ParseJob) -> JobStatusResponse:
        return JobStatusResponse(
            **job.model_dump(),
            status_label=PARSE_STATUS_LABELS[job.status.value],
            phase_label=PHASE_LABELS.get(job.phase, job.phase),
        )

    def _clear_active_job(self, job_id: str) -> None:
        with self._lock:
            self._active_jobs.pop(job_id, None)

    def _build_result_not_ready_error(self, job: ParseJob) -> AppError:
        if job.status == ParseStatus.failed:
            return AppError(
                "PARSE_FAILED",
                "job failed before result became available",
                status_code=409,
                details={
                    "job_id": job.job_id,
                    "status": job.status.value,
                    "phase": job.phase,
                    "last_error_code": job.last_error_code,
                    "retryable": job.retryable,
                    "job_error_message": job.error_message,
                },
                retryable=job.retryable,
                phase=job.phase,
                technical_message=job.error_message,
            )
        return AppError(
            "PARSE_NOT_READY",
            "result is not ready",
            status_code=409,
            details={
                "job_id": job.job_id,
                "status": job.status.value,
                "phase": job.phase,
                "progress": job.progress,
                "retryable": job.retryable,
            },
            retryable=job.status in PROCESSING_STATUSES,
            phase=job.phase,
        )

    def _infer_textbook_version(self, file_name: str) -> str:
        if "人教" in file_name:
            return "人教版"
        if "北师大" in file_name:
            return "北师大版"
        return "待确认版本"

    def get_result(self, job_id: str, approved_only: bool = False, include_review_records: bool = True) -> dict:
        job = self.get_job(job_id)
        if job.status not in {ParseStatus.reviewing, ParseStatus.completed}:
            raise self._build_result_not_ready_error(job)
        payload = self.result_repo.get(job_id)
        if not payload:
            raise self._build_result_not_ready_error(job)
        filtered = self._filter_payload(payload, approved_only=approved_only)
        if not include_review_records:
            filtered["review_records"] = []
        return filtered

    def get_unit_result(self, job_id: str, unit_id: str, approved_only: bool = False) -> dict:
        payload = self.get_result(job_id, approved_only=approved_only, include_review_records=False)
        for unit_package in payload["units"]:
            if unit_package["unit"]["unit_id"] == unit_id:
                return unit_package
        raise AppError("UNIT_NOT_FOUND", "unit_id does not exist", status_code=404)

    def get_overview(self, limit: int = 8) -> dict:
        jobs = sorted(self.job_repo.list(), key=lambda item: item.created_at, reverse=True)
        exports = sorted(
            self.export_repo.list_metadata(),
            key=lambda item: item.get("created_at", ""),
            reverse=True,
        )
        status_counts = {status.value: 0 for status in ParseStatus}
        review_status_totals = {status.value: 0 for status in ReviewStatus}
        content_totals = {
            "units": 0,
            "vocabulary_items": 0,
            "sentence_patterns": 0,
            "dialogue_samples": 0,
            "unit_tasks": 0,
            "unit_prompts": 0,
        }
        review_record_total = 0
        jobs_with_results = 0
        recent_jobs: list[dict] = []

        for job in jobs:
            status_counts[job.status.value] += 1
            stored_result = self.result_repo.get(job.job_id)
            result = stored_result if job.status in {ParseStatus.reviewing, ParseStatus.completed} else None
            review_records = self.review_repo.get(job.job_id)
            result_summary = self._summarize_result(result)
            review_summary = self._summarize_review(result)
            review_state = self._derive_review_state(bool(result), review_summary)

            if result:
                jobs_with_results += 1

            review_record_total += len(review_records)
            for key in content_totals:
                content_totals[key] += result_summary[key]
            for key in review_status_totals:
                review_status_totals[key] += review_summary[key]

            recent_jobs.append(
                {
                    "job_id": job.job_id,
                    "file_name": job.file_name,
                    "created_at": job.created_at,
                    "started_at": job.started_at,
                    "finished_at": job.finished_at,
                    "updated_at": job.updated_at,
                    "status": job.status.value,
                    "status_label": PARSE_STATUS_LABELS[job.status.value],
                    "progress": job.progress,
                    "phase": job.phase,
                    "phase_label": PHASE_LABELS.get(job.phase, job.phase),
                    "phase_message": job.phase_message,
                    "page_total": job.page_total,
                    "page_done": job.page_done,
                    "unit_total": job.unit_total,
                    "unit_done": job.unit_done,
                    "retry_count": job.retry_count,
                    "last_error_code": job.last_error_code,
                    "retryable": job.retryable,
                    "preflight": job.preflight.model_dump(mode="json"),
                    "has_result": bool(result),
                    "review_state": review_state,
                    "review_state_label": REVIEW_STATE_LABELS[review_state],
                    "review_progress_text": f"{review_summary['approved']}/{review_summary['total'] or 0}",
                    "review_counts": review_summary,
                    "result_counts": result_summary,
                    "review_records": len(review_records),
                    "links": {
                        "job": f"/jobs/{job.job_id}",
                        "result": f"/results/{job.job_id}",
                        "review": f"/review/{job.job_id}",
                    },
                }
            )

        processing_jobs = sum(
            status_counts[key]
            for key in [
                ParseStatus.queued.value,
                ParseStatus.parsing.value,
                ParseStatus.structuring.value,
                ParseStatus.generating.value,
            ]
        )
        return {
            "generated_at": _now_iso(),
            "share_path": "/overview",
            "summary": {
                "total_jobs": len(jobs),
                "jobs_with_results": jobs_with_results,
                "processing_jobs": processing_jobs,
                "reviewing_jobs": status_counts[ParseStatus.reviewing.value],
                "failed_jobs": status_counts[ParseStatus.failed.value],
                "total_exports": len(exports),
                "review_records": review_record_total,
            },
            "status_counts": [
                {"key": key, "label": PARSE_STATUS_LABELS[key], "count": count}
                for key, count in status_counts.items()
            ],
            "review_status_totals": [
                {
                    "key": key,
                    "label": {
                        ReviewStatus.pending.value: "待审核",
                        ReviewStatus.approved.value: "已通过",
                        ReviewStatus.rejected.value: "已驳回",
                        ReviewStatus.revised.value: "已返修",
                    }[key],
                    "count": count,
                }
                for key, count in review_status_totals.items()
            ],
            "content_totals": content_totals,
            "recent_jobs": recent_jobs[:limit],
            "recent_exports": exports[:5],
            "design_flow": [
                {
                    "title": "上传教材",
                    "description": "上传英文教材 PDF，创建解析任务并记录任务 ID。",
                    "surface": "首页上传表单 / API",
                    "endpoint": "/api/v1/upload",
                },
                {
                    "title": "解析与结构化",
                    "description": "执行 PDF 读取、OCR、版面分析、单元检测和板块抽取，生成结构化内容。",
                    "surface": "任务状态页 / 结果页",
                    "endpoint": "/api/v1/parse/{job_id}",
                },
                {
                    "title": "审核修改",
                    "description": "对单元、词汇、句型、对话、任务和 Prompt 逐项审核并记录轨迹。",
                    "surface": "审核页 / 审核 API",
                    "endpoint": "/api/v1/review/items/{target_type}/{target_id}",
                },
                {
                    "title": "导出交付",
                    "description": "按审核状态导出 JSON、Markdown 或 Excel，形成可下载结果文件。",
                    "surface": "导出 API",
                    "endpoint": "/api/v1/export",
                },
            ],
        }

    def export_result(self, request: ExportRequest) -> dict:
        payload = self.get_result(request.job_id, approved_only=False, include_review_records=True)
        if request.unit_ids:
            payload = self._filter_payload_by_unit_ids(payload, request.unit_ids)
        if request.approved_only:
            blocked = self._collect_non_approved(payload)
            if blocked:
                raise AppError(
                    "EXPORT_BLOCKED",
                    "there are pending or rejected items",
                    status_code=409,
                    details={"blocked_items": blocked},
                )
            payload = self._filter_payload(payload, approved_only=True)

        export_id = f"exp_{uuid4().hex[:10]}"
        output_path = self.export_dir / f"{export_id}.{request.format}"
        payload["export_meta"]["export_scope"] = request.export_scope or ("units" if request.unit_ids else "book")
        payload["export_meta"]["approved_only"] = request.approved_only
        payload["export_meta"]["unit_ids"] = [package["unit"]["unit_id"] for package in payload["units"]]
        payload["export_meta"]["exported_at"] = _now_iso()
        if request.format == "json":
            export_json(payload, output_path)
        elif request.format == "markdown":
            export_markdown(payload, output_path)
        elif request.format == "xlsx":
            export_xlsx(payload, output_path)
        else:
            raise AppError("INVALID_REQUEST", "unsupported export format", status_code=400)

        metadata = {
            "export_id": export_id,
            "job_id": request.job_id,
            "status": "completed",
            "format": request.format,
            "file_path": str(output_path),
            "download_url": f"/api/v1/export/{export_id}/download",
            "created_at": _now_iso(),
        }
        self.export_repo.save_metadata(export_id, metadata)
        return metadata

    def get_export_metadata(self, export_id: str) -> dict:
        metadata = self.export_repo.get_metadata(export_id)
        if not metadata:
            raise AppError("TARGET_NOT_FOUND", "export does not exist", status_code=404)
        return metadata

    def _filter_payload(self, payload: dict, approved_only: bool) -> dict:
        if not approved_only:
            return deepcopy(payload)
        filtered = deepcopy(payload)
        filtered["units"] = []
        for unit_package in payload["units"]:
            if unit_package["unit"]["review_status"] != ReviewStatus.approved.value:
                continue
            cloned = deepcopy(unit_package)
            cloned["vocabulary"] = [item for item in cloned["vocabulary"] if item["review_status"] == ReviewStatus.approved.value]
            cloned["sentence_patterns"] = [
                item for item in cloned["sentence_patterns"] if item["review_status"] == ReviewStatus.approved.value
            ]
            cloned["dialogue_samples"] = [
                item for item in cloned["dialogue_samples"] if item["review_status"] == ReviewStatus.approved.value
            ]
            if cloned["unit_task"]["review_status"] != ReviewStatus.approved.value:
                continue
            if cloned["unit_prompt"]["review_status"] != ReviewStatus.approved.value:
                continue
            filtered["units"].append(cloned)
        filtered["review_records"] = [
            record for record in filtered["review_records"] if record["review_status"] == ReviewStatus.approved.value
        ]
        return filtered

    def _filter_payload_by_unit_ids(self, payload: dict, unit_ids: list[str]) -> dict:
        filtered = deepcopy(payload)
        selected = [unit_package for unit_package in filtered["units"] if unit_package["unit"]["unit_id"] in set(unit_ids)]
        if unit_ids and not selected:
            raise AppError("UNIT_NOT_FOUND", "unit_id does not exist", status_code=404)
        filtered["units"] = selected
        visible_target_ids = {target["book_id"] for target in [filtered["book"]]}
        for target in self._iter_review_targets(filtered):
            visible_target_ids.update(
                target.get(key)
                for key in ["unit_id", "item_id", "book_id"]
                if target.get(key)
            )
        filtered["review_records"] = [
            record for record in filtered.get("review_records", []) if record.get("target_id") in visible_target_ids
        ]
        return filtered

    def _collect_non_approved(self, payload: dict) -> list[dict]:
        blocked: list[dict] = []
        if payload["book"]["review_status"] != ReviewStatus.approved.value:
            blocked.append({"target_type": "book", "target_id": payload["book"]["book_id"]})
        for unit_package in payload["units"]:
            unit = unit_package["unit"]
            if unit["review_status"] != ReviewStatus.approved.value:
                blocked.append({"target_type": "unit", "target_id": unit["unit_id"]})
            for key, target_type in [
                ("vocabulary", "vocabulary_item"),
                ("sentence_patterns", "sentence_pattern"),
                ("dialogue_samples", "dialogue_sample"),
            ]:
                for item in unit_package[key]:
                    if item["review_status"] != ReviewStatus.approved.value:
                        blocked.append({"target_type": target_type, "target_id": item["item_id"]})
            for key, target_type in [("unit_task", "unit_task"), ("unit_prompt", "unit_prompt")]:
                item = unit_package[key]
                if item["review_status"] != ReviewStatus.approved.value:
                    blocked.append({"target_type": target_type, "target_id": item["item_id"]})
        return blocked

    def _summarize_result(self, payload: dict | None) -> dict:
        if not payload:
            return {
                "units": 0,
                "vocabulary_items": 0,
                "sentence_patterns": 0,
                "dialogue_samples": 0,
                "unit_tasks": 0,
                "unit_prompts": 0,
            }
        unit_packages = payload.get("units", [])
        return {
            "units": len(unit_packages),
            "vocabulary_items": sum(len(package.get("vocabulary", [])) for package in unit_packages),
            "sentence_patterns": sum(len(package.get("sentence_patterns", [])) for package in unit_packages),
            "dialogue_samples": sum(len(package.get("dialogue_samples", [])) for package in unit_packages),
            "unit_tasks": sum(1 for package in unit_packages if package.get("unit_task")),
            "unit_prompts": sum(1 for package in unit_packages if package.get("unit_prompt")),
        }

    def _summarize_review(self, payload: dict | None) -> dict:
        counts = {status.value: 0 for status in ReviewStatus}
        if not payload:
            counts["total"] = 0
            return counts
        for target in self._iter_review_targets(payload):
            status = target.get("review_status", ReviewStatus.pending.value)
            if status in counts:
                counts[status] += 1
        counts["total"] = sum(counts.values())
        return counts

    def _iter_review_targets(self, payload: dict) -> list[dict]:
        targets: list[dict] = []
        book = payload.get("book")
        if book:
            targets.append(book)
        for unit_package in payload.get("units", []):
            if unit_package.get("unit"):
                targets.append(unit_package["unit"])
            targets.extend(unit_package.get("vocabulary", []))
            targets.extend(unit_package.get("sentence_patterns", []))
            targets.extend(unit_package.get("dialogue_samples", []))
            if unit_package.get("unit_task"):
                targets.append(unit_package["unit_task"])
            if unit_package.get("unit_prompt"):
                targets.append(unit_package["unit_prompt"])
        return targets

    def _derive_review_state(self, has_result: bool, summary: dict) -> str:
        if not has_result:
            return "not_ready"
        if summary["total"] == 0:
            return "pending_review"
        if summary[ReviewStatus.approved.value] == summary["total"]:
            return "approved"
        if summary[ReviewStatus.rejected.value] > 0:
            return "has_rejections"
        if summary[ReviewStatus.revised.value] > 0:
            return "needs_revision"
        return "pending_review"
