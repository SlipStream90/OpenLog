"""Agent-agnostic token pricing table -- shared cost estimation.

Holds the user's `~/.ai-observatory/pricing.json` table (USD per million
tokens, longest-prefix model match) and the honest-empty default: prices are
an external fact, so the table ships empty and `estimated_cost` stays `0.0`
until the user supplies real numbers. The dashboard says "No pricing
configured" rather than implying the day was free.

This lives in `shared` (not under one agent's adapter) so `backend.api` can
answer "is anything priced?" without importing a concrete adapter module --
per-adapter pricing stays behind each adapter's own `estimate_cost`, which
delegates here.
"""

from __future__ import annotations

import json
import logging

from backend.shared import paths

logger = logging.getLogger(__name__)

#: Deliberately empty -- prices are user-supplied, never recalled.
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
