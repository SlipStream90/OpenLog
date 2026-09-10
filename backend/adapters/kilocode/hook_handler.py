#!/usr/bin/env python3
"""Kilo Code hook entrypoint. STDLIB ONLY -- thin shim.

Same contract as the other adapters: invoked synchronously mid-session, one
append, always exit 0 (ADR-007). All behavior lives in
`backend/adapters/_hook_common.py`; this file only puts that module on
`sys.path` and names this agent's queue file.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from _hook_common import run

if __name__ == "__main__":
    sys.exit(run(("logs", "kilocode_hooks.jsonl")))
