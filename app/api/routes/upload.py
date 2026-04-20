from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile

from app.api.deps import get_job_service
from app.core.config import get_settings
from app.core.errors import AppError
from app.schemas.common import ApiResponse
from app.services.job_service import JobService

router = APIRouter(tags=["upload"])


@router.post("/upload", response_model=ApiResponse)
async def upload_pdf(
    file: UploadFile = File(...),
    service: JobService = Depends(get_job_service),
):
    settings = get_settings()
    if not file.filename:
        raise AppError("FILE_REQUIRED", "file is required", status_code=400)
    if not file.filename.lower().endswith(".pdf"):
        raise AppError("UNSUPPORTED_FILE_TYPE", "only pdf files are supported", status_code=400)
    content = await file.read()
    if len(content) > settings.max_upload_size_mb * 1024 * 1024:
        raise AppError("FILE_TOO_LARGE", "file exceeds size limit", status_code=400)
    job = service.create_job(file.filename, content)
    return ApiResponse(data=job.model_dump(mode="json"))
