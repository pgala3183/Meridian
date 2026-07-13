"""Ask / Q&A schemas for the demo chat UI."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class CitationOut(BaseModel):
    start_time: float
    end_time: float
    transcript_excerpt: str
    chunk_id: str | None = None


class AskResponse(BaseModel):
    answer: str
    citations: list[CitationOut]
    job_id: str
    model: str | None = None
