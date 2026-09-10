"""Redact secrets from terminal command text before it is stored.

PRD section 21 forbids persisting terminal history off-machine, and even
within the local database, secrets in argv (`export KEY=...`,
`curl -H "Authorization: Bearer ..."`, `https://user:pass@host`) must not be
kept verbatim. Every adapter's `_map_shell_command` passes the observed
command through `sanitize_command()` so the `Command.command` column and the
`Event.metadata["command"]` copies hold the redacted form only.

Design notes:

* Deterministic regex redaction, stdlib only, no network, no ML.
* Idempotent: running it twice changes nothing the second time, so the
  ingestion layer can apply it again as belt-and-braces without corrupting
  already-redacted text.
* Conservative: unknown shapes pass through untouched. A missed secret is a
  known residual risk (documented, not silent); a mangled normal command
  would corrupt the Commands/Tests metrics, which is worse.
"""

from __future__ import annotations

import re

REDACTED = "[REDACTED]"

#: Sensitive environment variable / flag names (matched case-insensitively).
#: Hyphenated variants cover `--db-password secret` style CLI flags.
_SENSITIVE_NAMES = (
    "api_key",
    "api-key",
    "apikey",
    "auth",
    "authorization",
    "aws_secret",
    "client_secret",
    "client-secret",
    "credentials",
    "db_password",
    "db-password",
    "dbpassword",
    "gh_token",
    "github_token",
    "github-token",
    "key",
    "openai_api_key",
    "passwd",
    "password",
    "private_key",
    "private-key",
    "secret",
    "session_token",
    "session-token",
    "token",
)

_NAME_ALT = "|".join(_SENSITIVE_NAMES)

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # export FOO=secret / FOO=secret (shell env assignments, incl. `env FOO=x cmd`).
    (
        re.compile(
            rf"(?i)((?:^|[\s;&|])(?:export\s+)?)({_NAME_ALT})\s*=\s*"
            r"(\"[^\"]*\"|'[^']*'|[^\s;&|\"']+)",
        ),
        lambda m: f"{m.group(1)}{m.group(2)}={REDACTED}",
    ),
    # --flag=secret / --flag secret for sensitive flag names.
    (
        re.compile(rf"(?i)(--(?:{_NAME_ALT}))\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s]+)"),
        lambda m: f"{m.group(1)}={REDACTED}",
    ),
    (
        re.compile(rf"(?i)(--(?:{_NAME_ALT}))\s+(\"[^\"]*\"|'[^']*'|[^\s-][^\s]*)"),
        lambda m: f"{m.group(1)} {REDACTED}",
    ),
    # Authorization: Bearer xyz / Basic xyz (curl -H headers included).
    (
        re.compile(r"(?i)(authorization\s*:\s*)(Bearer|Basic|Token)\s+[^\s\"']+"),
        lambda m: f"{m.group(1)}{m.group(2)} {REDACTED}",
    ),
    # https://user:password@host -> keep the user, drop the password.
    (
        re.compile(r"(https?://[^/\s:]+:)([^@\s/]+)(@)"),
        lambda m: f"{m.group(1)}{REDACTED}{m.group(3)}",
    ),
    # Well-known token prefixes.
    (re.compile(r"sk-[A-Za-z0-9\-_]{8,}"), REDACTED),
    (re.compile(r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{8,}"), REDACTED),
    (re.compile(r"github_pat_[A-Za-z0-9_]{8,}"), REDACTED),
    (re.compile(r"xox[bap]-?[A-Za-z0-9\-]{8,}"), REDACTED),
    (re.compile(r"AKIA[0-9A-Z]{16}"), REDACTED),
)


def sanitize_command(command: str | None) -> str | None:
    """Return `command` with secret values replaced by `[REDACTED]`."""
    if not isinstance(command, str) or not command:
        return command
    text = command
    for pattern, replacement in _PATTERNS:
        try:
            text = pattern.sub(replacement, text)  # type: ignore[arg-type]
        except re.error:
            continue
    return text
