"""Kilo Code adapter — observes the Kilo Code VS Code extension.

Kilo Code is a fork of Roo Code / Cline. It runs inside VS Code and exposes
events via the extension host. This adapter tails its log files; all
[KILOCADE-UNVERIFIED] shapes are confined here.
"""

from backend.adapters.kilocode.adapter import KiloCodeAdapter

__all__ = ["KiloCodeAdapter"]
