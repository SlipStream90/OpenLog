"""FastAPI routers -- exactly the five endpoints MISSION_BRIEF.md authorizes.

No /charts, /recommendations or /search: those are Milestone 3/4 (PRD section 17
lists them, the brief explicitly defers them).
"""

from backend.api.routers import files, sessions, stats, timeline

__all__ = ["files", "sessions", "stats", "timeline"]
