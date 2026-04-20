from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from app.api.deps import get_job_service
from app.schemas.common import ApiResponse
from app.schemas.export import ExportRequest
from app.services.job_service import JobService

router = APIRouter(tags=["export"])


@router.post("/export", response_model=ApiResponse)
def export_result(
    request: ExportRequest,
    service: JobService = Depends(get_job_service),
):
    metadata = service.export_result(request)
    return ApiResponse(data=metadata)


@router.get("/export/{export_id}/download")
def download_export(export_id: str, service: JobService = Depends(get_job_service)):
    metadata = service.get_export_metadata(export_id)
    return FileResponse(
        path=metadata["file_path"],
        filename=f"{export_id}.{metadata['format']}",
        media_type="application/octet-stream",
    )
