"""Token cost estimation (Claude).

Thin wrapper over `backend.shared.pricing`: the table format, the honest-empty
default and the longest-prefix match are agent-agnostic and live there, so
`backend.api` can ask "is anything priced?" without importing this module.
Kept so existing imports (`backend.adapters.claude.pricing`) keep working.
"""

from __future__ import annotations

from backend.shared.pricing import (
    DEFAULT_PRICING,
    estimate_cost,
    is_priced,
    load_pricing,
    pricing_path,
    reset_cache,
)

__all__ = [
    "DEFAULT_PRICING",
    "estimate_cost",
    "is_priced",
    "load_pricing",
    "pricing_path",
    "reset_cache",
]
