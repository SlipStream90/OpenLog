"""FastAPI routers -- the read-only local API (PRD section 17).

Sessions, timeline, files and stats are Milestones 1-2; search, charts,
analytics and export extend the same read-only pattern with no new tables.
"""

from backend.api.routers import (
    analytics,
    charts,
    export,
    files,
    search,
    sessions,
    stats,
    timeline,
)

__all__ = [
    "analytics",
    "charts",
    "export",
    "files",
    "search",
    "sessions",
    "stats",
    "timeline",
]
