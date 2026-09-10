"""OpenCode adapter.

All [UNVERIFIED] assumptions about OpenCode's payload shapes are confined to
this package. If those shapes differ from what is assumed, only this package
needs to change — the telemetry, database, and API layers remain agnostic.
"""

from backend.adapters.opencode.adapter import OpenCodeAdapter

__all__ = ["OpenCodeAdapter"]
