"""Agent-agnostic types shared across the adapter, telemetry and database layers."""

from backend.shared.events import EventType, UniversalEvent

__all__ = ["EventType", "UniversalEvent"]
