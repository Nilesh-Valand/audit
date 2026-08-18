from __future__ import annotations

import os
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.ai_content.analyzer import analyze_text
from app.ai_content.suggestions import generate_suggestions

# Mirrors the standalone AI Content Detection API's contract exactly
# (GET /health, POST /analyze) so anything pointed at that service can be
# repointed at this backend instead — no separate process required.
router = APIRouter(tags=["ai-content"])


class AnalyzeRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=20000)
    include_suggestions: bool = True


class DetectedPatternResponse(BaseModel):
    pattern: str
    severity: Literal["Low", "Medium", "High"]
    score: float
    examples: list[str] = []


class SentenceScoreResponse(BaseModel):
    index: int
    text: str
    ai_likelihood: float


class SuggestionResponse(BaseModel):
    detected_sentence: str | None = None
    issue: str
    suggestion: str
    improved_direction: str | None = None


class OverallResultResponse(BaseModel):
    ai_writing_likelihood: float
    confidence: Literal["Low", "Medium", "High"]


class AnalyzeResponse(BaseModel):
    overall: OverallResultResponse
    detected_patterns: list[DetectedPatternResponse]
    sentence_scores: list[SentenceScoreResponse]
    highlighted_phrases: list[str]
    suggestions: list[SuggestionResponse]


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(payload: AnalyzeRequest) -> AnalyzeResponse:
    text = payload.content.strip()
    if not text:
        raise HTTPException(status_code=400, detail="content must not be empty")

    result = analyze_text(text)

    suggestions: list[dict] = []
    if payload.include_suggestions:
        suggestions = generate_suggestions(
            result["sentence_scores"],
            result["detected_patterns"],
            use_llm=bool(os.environ.get("GROQ_API_KEY")),
        )

    return AnalyzeResponse(
        overall=OverallResultResponse(
            ai_writing_likelihood=result["overall_pct"],
            confidence=result["confidence"],
        ),
        detected_patterns=result["detected_patterns"],
        sentence_scores=result["sentence_scores"],
        highlighted_phrases=result["highlighted_phrases"],
        suggestions=suggestions,
    )
