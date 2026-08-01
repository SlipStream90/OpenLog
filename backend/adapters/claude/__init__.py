"""Claude Code adapter.

Every [UNVERIFIED] assumption about Claude Code's hook payload shape, transcript
schema and settings format is confined to this package (ARCHITECTURE.md section
7). If those shapes differ from what is assumed, only this package changes.
"""

from backend.adapters.claude.adapter import ClaudeAdapter

__all__ = ["ClaudeAdapter"]
