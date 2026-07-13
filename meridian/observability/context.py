"""Request / job correlation IDs via contextvars."""

from __future__ import annotations

from contextvars import ContextVar, Token

_request_id: ContextVar[str | None] = ContextVar("meridian_request_id", default=None)
_job_id: ContextVar[str | None] = ContextVar("meridian_job_id", default=None)


def get_request_id() -> str | None:
    return _request_id.get()


def get_job_id() -> str | None:
    return _job_id.get()


def set_request_id(value: str | None) -> Token[str | None]:
    return _request_id.set(value)


def set_job_id(value: str | None) -> Token[str | None]:
    return _job_id.set(value)


def clear_context() -> None:
    _request_id.set(None)
    _job_id.set(None)
