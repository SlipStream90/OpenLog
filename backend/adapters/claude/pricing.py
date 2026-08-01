"""Token cost estimation.

## Why this table ships empty

`Sessions.estimated_cost` (PRD section 13) needs per-model token prices. Those
prices are an external fact that changes over time, and **every route to verify
current pricing was blocked in this session** (`context7`, `WebSearch`,
`WebFetch` all denied by the permission gate).

Hard-coding prices from recall would put a confident-looking dollar figure on the
dashboard that could be wrong by a large factor -- and a wrong cost is worse than
no cost, because the user cannot tell it is wrong. That is precisely the failure
mode PRD.md section 4 rejects ("a fabricated-looking placeholder is worse than an
honest gap").

So: the table is empty by default, `estimated_cost` stays `0.0`, and the
dashboard shows `$0.00` with an "unpriced" note. The user supplies real prices by
creating `~/.ai-observatory/pricing.json`:

```json
{
  "claude-sonnet-4-5": {"input_per_mtok": 3.00, "output_per_mtok": 15.00}
}
```

Prices are USD per million tokens. Model keys are matched by longest prefix, so
`"claude-sonnet"` covers every dated snapshot of that model.

TODO(BOND): once external verification is available, decide whether to ship a
default table. That is a product call, not one this agent should make silently.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.shared import paths

logger = logging.getLogger(__name__)

#: Deliberately empty -- see the module docstring.
DEFAULT_PRICING: dict[str, dict[str, float]] = {}

_cache: dict[str, dict[str, float]] | None = None


def pricing_path():
    return paths.root() / "pricing.json"


def load_pricing(force: bool = False) -> dict[str, dict[str, float]]:
    """Load the user's pricing table, falling back to empty."""
    global _cache
    if _cache is not None and not force:
        return _cache

    table = dict(DEFAULT_PRICING)
    path = pricing_path()
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for model, prices in data.items():
                    if isinstance(prices, dict):
                        table[str(model)] = {
                            "input_per_mtok": float(prices.get("input_per_mtok", 0.0)),
                            "output_per_mtok": float(prices.get("output_per_mtok", 0.0)),
                        }
    except (OSError, ValueError, TypeError) as exc:
        # A malformed pricing file must not stop telemetry ingestion.
        logger.warning("Ignoring unreadable pricing file %s: %s", path, exc)

    _cache = table
    return table


def is_priced() -> bool:
    """True when at least one model has a price, so the UI can say so honestly."""
    return bool(load_pricing())


def estimate_cost(model: str | None, input_tokens: int, output_tokens: int) -> float:
    """USD estimate for one exchange. Returns 0.0 when the model is unpriced."""
    if not model:
        return 0.0
    table = load_pricing()
    if not table:
        return 0.0

    best_key = None
    for key in table:
        if model.startswith(key) and (best_key is None or len(key) > len(best_key)):
            best_key = key
    if best_key is None:
        logger.debug("No price entry for model %r; cost recorded as 0.0", model)
        return 0.0

    prices = table[best_key]
    return (
        input_tokens / 1_000_000 * prices.get("input_per_mtok", 0.0)
        + output_tokens / 1_000_000 * prices.get("output_per_mtok", 0.0)
    )


def reset_cache() -> None:
    """Drop the cached table (tests)."""
    global _cache
    _cache = None
