from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_review_service
from app.schemas.common import ApiResponse
from app.schemas.review import BatchReviewRequest, ReviewItemRequest
from app.services.reviewer.review_service import ReviewService

router = APIRouter(tags=["review"])


@router.patch("/review/items/{target_type}/{target_id}", response_model=ApiResponse)
def review_item(
    target_type: str,
    target_id: str,
    request: ReviewItemRequest,
    service: ReviewService = Depends(get_review_service),
):
    record = service.review_item(target_type, target_id, request)
    return ApiResponse(data=record)


@router.post("/review/units/{unit_id}/batch", response_model=ApiResponse)
def batch_review_unit(
    unit_id: str,
    request: BatchReviewRequest,
    service: ReviewService = Depends(get_review_service),
):
    payload = service.batch_review_unit(unit_id, request)
    return ApiResponse(data=payload)
