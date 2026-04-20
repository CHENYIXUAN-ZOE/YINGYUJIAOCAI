from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_job_service
from app.schemas.common import ApiResponse
from app.services.job_service import JobService

router = APIRouter(tags=["results"])


@router.get("/results/{job_id}", response_model=ApiResponse)
def get_result(
    job_id: str,
    approved_only: bool = False,
    include_review_records: bool = True,
    service: JobService = Depends(get_job_service),
):
    payload = service.get_result(job_id, approved_only=approved_only, include_review_records=include_review_records)
    return ApiResponse(data=payload)


@router.get("/results/{job_id}/units/{unit_id}", response_model=ApiResponse)
def get_unit_result(
    job_id: str,
    unit_id: str,
    approved_only: bool = False,
    service: JobService = Depends(get_job_service),
):
    payload = service.get_unit_result(job_id, unit_id, approved_only=approved_only)
    return ApiResponse(data=payload)
