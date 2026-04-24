from __future__ import annotations


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict | None = None,
        *,
        retryable: bool | None = None,
        phase: str | None = None,
        technical_message: str | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        self.retryable = status_code >= 500 if retryable is None else retryable
        self.phase = phase
        self.technical_message = technical_message
