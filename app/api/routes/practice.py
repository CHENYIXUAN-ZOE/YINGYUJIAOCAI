from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_practice_service
from app.schemas.common import ApiResponse
from app.schemas.practice import PracticeChatRequest, PracticeReportRequest
from app.services.practice_service import PracticeService

router = APIRouter(tags=["practice"])


@router.get("/practice/context", response_model=ApiResponse)
def get_practice_context(
    job_id: str,
    unit_id: str,
    service: PracticeService = Depends(get_practice_service),
):
    return ApiResponse(data=service.get_context(job_id, unit_id))


@router.post("/practice/chat", response_model=ApiResponse)
def practice_chat(
    request: PracticeChatRequest,
    service: PracticeService = Depends(get_practice_service),
):
    return ApiResponse(data=service.chat(request))


@router.post("/practice/report", response_model=ApiResponse)
def practice_report(
    request: PracticeReportRequest,
    service: PracticeService = Depends(get_practice_service),
):
    return ApiResponse(data=service.build_report(request))
