from __future__ import annotations

from contextlib import asynccontextmanager
import logging

from fastapi import Depends, FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes.export import router as export_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.practice import router as practice_router
from app.api.routes.results import router as results_router
from app.api.routes.review import router as review_router
from app.api.routes.upload import router as upload_router
from app.core.config import get_settings
from app.core.errors import AppError
from app.schemas.common import ErrorResponse
from app.services.job_service import JobService
from app.api.deps import get_job_service

settings = get_settings()
templates = Jinja2Templates(directory=str(settings.template_dir))
logger = logging.getLogger(__name__)

def _is_api_request(request: Request) -> bool:
    return request.url.path.startswith(settings.api_prefix)


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict | None = None,
    retryable: bool = False,
    phase: str | None = None,
    technical_message: str | None = None,
):
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(
            error={
                "code": code,
                "message": message,
                "details": details or {},
                "retryable": retryable,
                "phase": phase,
                "technical_message": technical_message,
            }
        ).model_dump(),
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    recovered_jobs = get_job_service().recover_incomplete_jobs()
    if recovered_jobs:
        logger.warning(
            "Recovered %s interrupted jobs on startup: %s",
            len(recovered_jobs),
            ", ".join(job.job_id for job in recovered_jobs),
        )
    yield


app = FastAPI(title=settings.project_name, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")

app.include_router(upload_router, prefix=settings.api_prefix)
app.include_router(jobs_router, prefix=settings.api_prefix)
app.include_router(results_router, prefix=settings.api_prefix)
app.include_router(practice_router, prefix=settings.api_prefix)
app.include_router(review_router, prefix=settings.api_prefix)
app.include_router(export_router, prefix=settings.api_prefix)


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError):
    return _error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
        retryable=exc.retryable,
        phase=exc.phase,
        technical_message=exc.technical_message,
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError):
    return _error_response(
        status_code=400,
        code="INVALID_REQUEST",
        message="request validation failed",
        details={"errors": exc.errors()},
    )


@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    if _is_api_request(request):
        message = exc.detail if isinstance(exc.detail, str) else "http error"
        code = f"HTTP_{exc.status_code}"
        return _error_response(status_code=exc.status_code, code=code, message=message)
    return await http_exception_handler(request, exc)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception for %s %s", request.method, request.url.path, exc_info=exc)
    if _is_api_request(request):
        return _error_response(
            status_code=500,
            code="INTERNAL_ERROR",
            message="internal server error",
            retryable=True,
            technical_message=str(exc),
        )
    return HTMLResponse("Internal Server Error", status_code=500)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "api_prefix": settings.api_prefix,
            "max_upload_size_mb": settings.max_upload_size_mb,
            "initial_job_id": request.query_params.get("job_id", ""),
            "initial_view": request.query_params.get("view", "overview"),
        },
    )


@app.get("/overview", response_class=HTMLResponse)
async def overview_page(request: Request, service: JobService = Depends(get_job_service)):
    return templates.TemplateResponse(
        request,
        "overview.html",
        {
            "request": request,
            "api_prefix": settings.api_prefix,
            "overview": service.get_overview(),
            "share_url": str(request.url_for("overview_page")),
        },
    )


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_page(request: Request, job_id: str):
    return templates.TemplateResponse(
        request,
        "job.html",
        {"request": request, "job_id": job_id, "api_prefix": settings.api_prefix},
    )


@app.get("/results/{job_id}", response_class=HTMLResponse)
async def result_page(request: Request, job_id: str):
    return templates.TemplateResponse(
        request,
        "result.html",
        {"request": request, "job_id": job_id, "api_prefix": settings.api_prefix},
    )


@app.get("/review/{job_id}", response_class=HTMLResponse)
async def review_page(request: Request, job_id: str):
    return templates.TemplateResponse(
        request,
        "review.html",
        {"request": request, "job_id": job_id, "api_prefix": settings.api_prefix},
    )


@app.get("/practice", response_class=HTMLResponse)
async def practice_page(request: Request):
    return templates.TemplateResponse(
        request,
        "practice.html",
        {
            "request": request,
            "api_prefix": settings.api_prefix,
            "initial_job_id": request.query_params.get("job_id", ""),
            "initial_unit_id": request.query_params.get("unit_id", ""),
        },
    )
