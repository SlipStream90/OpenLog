"""Analytics engine: productivity scoring and recommendations.

Milestone 3, implemented deterministically: every number is explainable and
every recommendation links back to its triggering metric. No ML, no network.
"""

from backend.analytics.productivity import (
    ScoredProductivity,
    SessionFactors,
    score_session,
)
from backend.analytics.recommendations import (
    Recommendation,
    RecommendationContext,
    build_context,
    recommend,
)

__all__ = [
    "ScoredProductivity",
    "SessionFactors",
    "score_session",
    "Recommendation",
    "RecommendationContext",
    "build_context",
    "recommend",
]
