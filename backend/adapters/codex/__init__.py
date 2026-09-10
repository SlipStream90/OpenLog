"""Codex CLI adapter (PRD sections 8, 10, 18).

Normalizes Codex hook + session payloads into Universal Events. Schema
assumptions are [UNVERIFIED] -- see `event_mapper.py`; all agent-specific
parsing stops at this package boundary.
"""
