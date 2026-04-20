from __future__ import annotations

from fastapi import Depends, FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes.export import router as export_router
from app.api.routes.jobs import router as jobs_router
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

app = FastAPI(title=settings.project_name)
app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")

app.include_router(upload_router, prefix=settings.api_prefix)
app.include_router(jobs_router, prefix=settings.api_prefix)
app.include_router(results_router, prefix=settings.api_prefix)
app.include_router(review_router, prefix=settings.api_prefix)
app.include_router(export_router, prefix=settings.api_prefix)


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(error={"code": exc.code, "message": exc.message, "details": exc.details}).model_dump(),
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content=ErrorResponse(
            error={
                "code": "INVALID_REQUEST",
                "message": "request validation failed",
                "details": {"errors": exc.errors()},
            }
        ).model_dump(),
    )


@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    return await http_exception_handler(request, exc)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "api_prefix": settings.api_prefix})


@app.get("/overview", response_class=HTMLResponse)
async def overview_page(request: Request, service: JobService = Depends(get_job_service)):
    return templates.TemplateResponse(
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
    return templates.TemplateResponse("job.html", {"request": request, "job_id": job_id, "api_prefix": settings.api_prefix})


@app.get("/results/{job_id}", response_class=HTMLResponse)
async def result_page(request: Request, job_id: str):
    return templates.TemplateResponse(
        "result.html",
        {"request": request, "job_id": job_id, "api_prefix": settings.api_prefix},
    )


@app.get("/review/{job_id}", response_class=HTMLResponse)
async def review_page(request: Request, job_id: str):
    return templates.TemplateResponse(
        "review.html",
        {"request": request, "job_id": job_id, "api_prefix": settings.api_prefix},
    )
