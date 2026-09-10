#!/usr/bin/env python3
"""Claude Code hook entrypoint. STDLIB ONLY -- thin shim.

Invoked synchronously by Claude Code on every hook event, mid-session. All
behavior lives in `backend/adapters/_hook_common.py` (one append, always exit
0, never surface anything: ADR-007); this file only puts that module on
`sys.path` and names this agent's queue file. That keeps the hot path
reviewed once instead of four times, without importing anything heavier than
stdlib into the hook process.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _hook_common import run

if __name__ == "__main__":
    # Always exit 0: Claude Code may treat a non-zero hook exit as a blocking
    # failure, and the brief forbids any user-visible interruption.
    sys.exit(run(("logs", "claude_hooks.jsonl")))
