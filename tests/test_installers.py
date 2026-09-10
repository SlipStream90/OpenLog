"""Thin JSON-shape installers (opencode/kilocode/codex) share one safety core.

Every test operates on in-memory dicts or `tmp_path` files -- never the
developer's real config. Claude's installer has its own entry shape and its
own test file (test_install_hooks.py).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"_installer_{name}", _REPO_ROOT / "scripts" / f"install_{name}_hooks.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("agent", ["opencode", "kilocode", "codex"])
def test_install_uninstall_round_trip(agent, tmp_path):
    installer = _load(agent)
    command = f'"/usr/bin/python3" "/repo/{installer.MARKER}"'

    settings, added = installer.install({}, command)
    assert added >= 1
    blob = json.dumps(settings)
    assert installer.MARKER in blob

    # Idempotent: a second install adds nothing.
    _, added_again = installer.install(settings, command)
    assert added_again == 0

    # Uninstall removes exactly what install added, keeps foreign keys.
    settings["foreign_key"] = {"keep": True}
    settings, removed = installer.uninstall(settings)
    assert removed == added
    assert installer.MARKER not in json.dumps(settings)
    assert settings["foreign_key"] == {"keep": True}


@pytest.mark.parametrize("agent", ["opencode", "kilocode", "codex"])
def test_main_dry_run_writes_nothing(agent, tmp_path, capsys):
    installer = _load(agent)
    target = tmp_path / "settings.json"
    target.write_text(json.dumps({"hooks": {}}), encoding="utf-8")

    import sys
    from unittest import mock

    with mock.patch.object(installer, "settings_path", return_value=target):
        rc = installer.main(["--dry-run", "--yes"])
    assert rc == 0
    # Dry run prints but writes nothing.
    assert json.loads(target.read_text(encoding="utf-8")) == {"hooks": {}}
    assert "hooks" in capsys.readouterr().out


def test_common_jsonc_tolerance(tmp_path):
    _load("opencode")  # thin wrapper insert puts scripts/ on sys.path
    import _hook_install_common as core

    path = tmp_path / "settings.json"
    path.write_text('{\n  // a comment\n  "hooks": {},\n}\n', encoding="utf-8")
    assert core.load_settings(path) == {"hooks": {}}

    path.write_text("not json at all", encoding="utf-8")
    with pytest.raises(SystemExit):
        core.load_settings(path)
