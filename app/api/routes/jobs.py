from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_job_service
from app.schemas.common import ApiResponse
from app.schemas.job import ParseRequest
from app.services.job_service import JobService

router = APIRouter(tags=["jobs"])


@router.post("/parse/{job_id}", response_model=ApiResponse)
def parse_job(
    job_id: str,
    request: ParseRequest,
    service: JobService = Depends(get_job_service),
):
    job = service.start_parse(job_id, force_reparse=request.force_reparse)
    return ApiResponse(data=job.model_dump(mode="json"))


@router.get("/jobs/{job_id}", response_model=ApiResponse)
def get_job_status(job_id: str, service: JobService = Depends(get_job_service)):
    return ApiResponse(data=service.get_job_status(job_id).model_dump(mode="json"))
