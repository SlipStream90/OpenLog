"""Secret redaction for terminal command text (PRD section 21).

`sanitize_command` must redact secret *values* while leaving normal commands
byte-identical, and it must be idempotent so layered callers (mapper +
ingestion) cannot corrupt already-redacted text.
"""

from __future__ import annotations

from backend.shared.sanitize import REDACTED, sanitize_command as s


def test_normal_commands_untouched():
    for cmd in (
        "uv run pytest -q",
        "git commit -m fix",
        "npm run build",
        "export PATH=/usr/bin:/bin",
        "monkey=business",
        "echo hello world",
        "cargo test -- --nocapture",
    ):
        assert s(cmd) == cmd, cmd


def test_env_assignments_redacted():
    assert s("export OPENAI_API_KEY=abc123") == f"export OPENAI_API_KEY={REDACTED}"
    assert s("API_KEY=foobar pytest") == f"API_KEY={REDACTED} pytest"
    assert s("export GH_TOKEN='secret value' && make") == f"export GH_TOKEN={REDACTED} && make"


def test_sensitive_flags_redacted():
    assert s("npm run deploy --token abcDEF123 --dry-run") == (
        f"npm run deploy --token {REDACTED} --dry-run"
    )
    assert s("psql --db-password=hunter2 -c 'select 1'") == (
        f"psql --db-password={REDACTED} -c 'select 1'"
    )


def test_auth_headers_and_urls_redacted():
    out = s('curl -H "Authorization: Bearer xyz123" https://api.example.com')
    assert "xyz123" not in out
    assert "Bearer" in out and REDACTED in out
    out = s("git clone https://user:s3cret@github.com/org/repo.git")
    assert "s3cret" not in out
    assert "https://user:" in out and REDACTED in out


def test_known_token_prefixes_redacted():
    assert REDACTED in s("openai --key sk-abc123XYZ789")
    assert REDACTED in s("gh auth login --with-token ghp_abcDEF123456")
    assert REDACTED in s("aws sts --key AKIAIOSFODNN7EXAMPLE")


def test_idempotent_and_none_safe():
    once = s("export KEY=x --token y https://u:p@h.io")
    assert s(once) == once
    assert s(None) is None
    assert s("") == ""
