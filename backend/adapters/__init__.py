"""Adapter layer.

Every agent-specific parsing detail lives inside a subpackage here. Nothing
outside `backend/adapters/` may branch on the agent name -- only UniversalEvent
crosses this boundary (PRD section 18).
"""
