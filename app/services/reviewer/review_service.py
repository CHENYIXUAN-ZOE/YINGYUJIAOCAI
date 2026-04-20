from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.core.errors import AppError
from app.repositories.result_repo import ResultRepository
from app.repositories.review_repo import ReviewRepository
from app.schemas.common import ContentTargetType, ReviewStatus
from app.schemas.review import BatchReviewRequest, ReviewItemRequest


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReviewService:
    def __init__(self, result_repo: ResultRepository, review_repo: ReviewRepository):
        self.result_repo = result_repo
        self.review_repo = review_repo

    def _all_results(self) -> list[tuple[str, dict]]:
        results = []
        for path in self.result_repo.base_dir.glob("*.json"):
            job_id = path.stem
            payload = self.result_repo.get(job_id)
            if payload:
                results.append((job_id, payload))
        return results

    def _find_target(self, payload: dict, target_type: str, target_id: str) -> dict | None:
        if target_type == ContentTargetType.book.value and payload["book"]["book_id"] == target_id:
            return payload["book"]
        for unit_package in payload["units"]:
            if target_type == ContentTargetType.unit.value and unit_package["unit"]["unit_id"] == target_id:
                return unit_package["unit"]
            if target_type == ContentTargetType.unit_task.value and unit_package["unit_task"]["item_id"] == target_id:
                return unit_package["unit_task"]
            if target_type == ContentTargetType.unit_prompt.value and unit_package["unit_prompt"]["item_id"] == target_id:
                return unit_package["unit_prompt"]
            if target_type == ContentTargetType.vocabulary_item.value:
                for item in unit_package["vocabulary"]:
                    if item["item_id"] == target_id:
                        return item
            if target_type == ContentTargetType.sentence_pattern.value:
                for item in unit_package["sentence_patterns"]:
                    if item["item_id"] == target_id:
                        return item
            if target_type == ContentTargetType.dialogue_sample.value:
                for item in unit_package["dialogue_samples"]:
                    if item["item_id"] == target_id:
                        return item
        return None

    def review_item(self, target_type: str, target_id: str, request: ReviewItemRequest) -> dict:
        for job_id, payload in self._all_results():
            target = self._find_target(payload, target_type, target_id)
            if not target:
                continue
            target["review_status"] = request.review_status.value
            for key, value in request.patched_fields.items():
                target[key] = value
            review_record = {
                "review_id": f"rev_{uuid4().hex[:10]}",
                "target_type": target_type,
                "target_id": target_id,
                "review_status": request.review_status.value,
                "review_notes": request.review_notes,
                "reviewer": request.reviewer,
                "reviewed_at": _now_iso(),
            }
            payload.setdefault("review_records", []).append(review_record)
            self.result_repo.save(job_id, payload)
            self.review_repo.save(job_id, payload["review_records"])
            return review_record
        raise AppError("TARGET_NOT_FOUND", "target does not exist", status_code=404)

    def batch_review_unit(self, unit_id: str, request: BatchReviewRequest) -> dict:
        updated = []
        for target in request.targets:
            record = self.review_item(
                target.target_type,
                target.target_id,
                ReviewItemRequest(
                    review_status=request.review_status,
                    review_notes=request.review_notes,
                    reviewer=request.reviewer,
                    patched_fields={},
                ),
            )
            updated.append(record)
        return {"unit_id": unit_id, "updated_reviews": updated}
