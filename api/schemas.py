from typing import Any
from pydantic import BaseModel, Field


class DiagnosisRequest(BaseModel):
    question: str = Field(min_length=5, max_length=2000)


class DiagnosisResponse(BaseModel):
    status: str
    mode: str
    question: str
    answer: str
    diagnostic: str | None = None
    read_only: bool = True
    metrics: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    quality_review: dict[str, Any] = Field(default_factory=dict)
    evidence_review: dict[str, Any] = Field(default_factory=dict)
