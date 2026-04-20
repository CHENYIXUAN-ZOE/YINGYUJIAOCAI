from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.core.errors import AppError
from app.repositories.export_repo import ExportRepository
from app.repositories.job_repo import JobRepository
from app.repositories.result_repo import ResultRepository
from app.repositories.review_repo import ReviewRepository
from app.schemas.common import GenerationMode, ParseStatus, ReviewStatus
from app.schemas.content import (
    Book,
    Classification,
    ExportMeta,
    StructuredContent,
    UnitPackage,
    UnitRecord,
)
from app.schemas.export import ExportRequest
from app.schemas.job import JobStatusResponse, ParseJob
from app.services.exporter.json_exporter import export_json
from app.services.exporter.markdown_exporter import export_markdown
from app.services.generator import dialogue_generator, prompt_generator, sentence_generator, task_generator, vocabulary_generator
from app.services.parser import (
    dialogue_extractor,
    layout_analyzer,
    ocr_processor,
    pdf_loader,
    section_classifier,
    sentence_extractor,
    unit_detector,
    vocabulary_extractor,
)

PARSE_STATUS_LABELS = {
    ParseStatus.uploaded.value: "已上传",
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
    ):
        self.upload_dir = upload_dir
        self.export_dir = export_dir
        self.job_repo = job_repo
        self.result_repo = result_repo
        self.review_repo = review_repo
        self.export_repo = export_repo

    def create_job(self, file_name: str, content: bytes) -> ParseJob:
        job_id = f"job_{uuid4().hex[:10]}"
        file_path = self.upload_dir / f"{job_id}_{file_name}"
        file_path.write_bytes(content)
        job = ParseJob(
            job_id=job_id,
            file_name=file_name,
            file_path=str(file_path),
            status=ParseStatus.uploaded,
            progress=0,
            created_at=_now_iso(),
            review_status=ReviewStatus.pending,
        )
        return self.job_repo.save(job)

    def get_job(self, job_id: str) -> ParseJob:
        job = self.job_repo.get(job_id)
        if not job:
            raise AppError("JOB_NOT_FOUND", "job_id does not exist", status_code=404)
        return job

    def get_job_status(self, job_id: str) -> JobStatusResponse:
        job = self.get_job(job_id)
        return JobStatusResponse(**job.model_dump())

    def start_parse(self, job_id: str, force_reparse: bool = False) -> ParseJob:
        job = self.get_job(job_id)
        if job.status not in {ParseStatus.uploaded, ParseStatus.failed, ParseStatus.completed} and not force_reparse:
            raise AppError("INVALID_REQUEST", "job is already processing", status_code=400)

        job.status = ParseStatus.parsing
        job.progress = 10
        self.job_repo.save(job)

        document = pdf_loader.load_pdf(Path(job.file_path))
        document = ocr_processor.process(document)
        document = layout_analyzer.analyze(document)
        units = unit_detector.detect(document)
        units = section_classifier.classify(document, units)

        job.status = ParseStatus.structuring
        job.progress = 45
        self.job_repo.save(job)

        result = self._build_result(job, document, units)
        self.result_repo.save(job_id, result)
        self.review_repo.save(job_id, result["review_records"])

        job.status = ParseStatus.reviewing
        job.progress = 100
        job.finished_at = _now_iso()
        self.job_repo.save(job)

        result["job"] = job.model_dump(mode="json")
        self.result_repo.save(job_id, result)
        return job

    def _build_result(self, job: ParseJob, document: dict, units: list[dict]) -> dict:
        textbook_version = self._infer_textbook_version(job.file_name)
        textbook_name = Path(job.file_name).stem
        book = Book(
            book_id=f"book_{job.job_id}",
            textbook_version=textbook_version,
            textbook_name=textbook_name,
            publisher=textbook_version,
            source_job_id=job.job_id,
            source_pages=[1],
            confidence=0.5,
            review_status=ReviewStatus.pending,
        )
        unit_packages: list[UnitPackage] = []
        for index, raw_unit in enumerate(units, start=1):
            classification = Classification(
                textbook_version=textbook_version,
                textbook_name=textbook_name,
                unit_code=raw_unit["unit_code"],
                unit_name=raw_unit["unit_name"],
            )
            unit_id = f"{job.job_id}_unit_{index}"
            unit_record = UnitRecord(
                unit_id=unit_id,
                classification=classification,
                unit_theme=raw_unit.get("unit_theme"),
                source_pages=raw_unit.get("source_pages", [1]),
                confidence=0.5,
                review_status=ReviewStatus.pending,
            )
            raw_vocab = vocabulary_extractor.extract(raw_unit)
            raw_patterns = sentence_extractor.extract(raw_unit)
            raw_dialogue = dialogue_extractor.extract(raw_unit)
            unit_packages.append(
                UnitPackage(
                    unit=unit_record,
                    vocabulary=vocabulary_generator.generate(classification, raw_vocab, unit_id),
                    sentence_patterns=sentence_generator.generate(classification, raw_patterns, unit_id),
                    dialogue_samples=dialogue_generator.generate(classification, raw_dialogue, unit_id),
                    unit_task=task_generator.generate(classification, unit_id),
                    unit_prompt=prompt_generator.generate(classification, unit_id),
                )
            )
        payload = StructuredContent(
            job=job.model_dump(mode="json"),
            book=book,
            units=unit_packages,
            review_records=[],
            export_meta=ExportMeta(
                schema_version="v1",
                export_scope="book",
                approved_only=True,
                unit_ids=[package.unit.unit_id for package in unit_packages],
            ),
        )
        return payload.model_dump(mode="json")

    def _infer_textbook_version(self, file_name: str) -> str:
        if "人教" in file_name:
            return "人教版"
        if "北师大" in file_name:
            return "北师大版"
        return "待确认版本"

    def get_result(self, job_id: str, approved_only: bool = False, include_review_records: bool = True) -> dict:
        self.get_job(job_id)
        payload = self.result_repo.get(job_id)
        if not payload:
            raise AppError("PARSE_NOT_READY", "result is not ready", status_code=409)
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
            result = self.result_repo.get(job.job_id)
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
                    "finished_at": job.finished_at,
                    "status": job.status.value,
                    "status_label": PARSE_STATUS_LABELS[job.status.value],
                    "progress": job.progress,
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
                    "description": "按审核状态导出 JSON 或 Markdown，形成可下载结果文件。",
                    "surface": "导出 API",
                    "endpoint": "/api/v1/export",
                },
            ],
        }

    def export_result(self, request: ExportRequest) -> dict:
        payload = self.get_result(request.job_id, approved_only=False, include_review_records=True)
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
        if request.format == "json":
            export_json(payload, output_path)
        elif request.format == "markdown":
            export_markdown(payload, output_path)
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
