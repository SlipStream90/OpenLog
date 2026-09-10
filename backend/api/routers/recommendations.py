"""`GET /recommendations` -- rule-based insights (PRD section 16)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session as SASession

from backend.analytics.recommendations import build_context, recommend
from backend.database.session import get_db

router = APIRouter(tags=["recommendations"])


class RecommendationModel(BaseModel):
    rule_id: str
    severity: str
    message: str
    metric: dict[str, Any] = {}


class RecommendationsResponse(BaseModel):
    recommendations: list[RecommendationModel] = []


@router.get("/recommendations", response_model=RecommendationsResponse)
def get_recommendations(db: SASession = Depends(get_db)) -> RecommendationsResponse:  # noqa: B008
    """Current digest. Empty list (not 404) when there is nothing to say yet."""
    recs = recommend(build_context(db))
    return RecommendationsResponse(
        recommendations=[
            RecommendationModel(
                rule_id=r.rule_id,
                severity=r.severity,
                message=r.message,
                metric=r.metric,
            )
            for r in recs
        ]
    )
