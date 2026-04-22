from functools import lru_cache

from app.clients.openai_compatible.practice_chat_client import OpenAICompatiblePracticeChatClient
from app.core.config import get_settings
from app.repositories.export_repo import ExportRepository
from app.repositories.job_repo import JobRepository
from app.repositories.result_repo import ResultRepository
from app.repositories.review_repo import ReviewRepository
from app.services.job_service import JobService
from app.services.practice_service import PracticeService
from app.services.reviewer.review_service import ReviewService


@lru_cache
def get_job_repo() -> JobRepository:
    return JobRepository(get_settings())


@lru_cache
def get_result_repo() -> ResultRepository:
    return ResultRepository(get_settings())


@lru_cache
def get_review_repo() -> ReviewRepository:
    return ReviewRepository(get_settings())


@lru_cache
def get_export_repo() -> ExportRepository:
    return ExportRepository(get_settings())


@lru_cache
def get_job_service() -> JobService:
    settings = get_settings()
    return JobService(
        upload_dir=settings.upload_dir,
        export_dir=settings.export_dir,
        job_repo=get_job_repo(),
        result_repo=get_result_repo(),
        review_repo=get_review_repo(),
        export_repo=get_export_repo(),
    )


@lru_cache
def get_openai_compatible_practice_client() -> OpenAICompatiblePracticeChatClient:
    return OpenAICompatiblePracticeChatClient(get_settings())


@lru_cache
def get_practice_service() -> PracticeService:
    return PracticeService(get_job_service(), get_openai_compatible_practice_client())


@lru_cache
def get_review_service() -> ReviewService:
    return ReviewService(get_result_repo(), get_review_repo())
