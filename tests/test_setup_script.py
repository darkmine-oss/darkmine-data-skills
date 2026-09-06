# SPDX-License-Identifier: GPL-3.0-or-later

import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "skills" / "setup" / "scripts" / "run_setup.py"
SPEC = importlib.util.spec_from_file_location("run_setup", SCRIPT_PATH)
RUN_SETUP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN_SETUP)


def test_venv_python_uses_scripts_layout_on_windows(monkeypatch):
    monkeypatch.setattr(RUN_SETUP, "WINDOWS", True)
    assert RUN_SETUP._venv_python(Path("repo") / ".venv") == Path("repo") / ".venv" / "Scripts" / "python.exe"


def test_venv_python_uses_bin_layout_elsewhere(monkeypatch):
    monkeypatch.setattr(RUN_SETUP, "WINDOWS", False)
    assert RUN_SETUP._venv_python(Path("repo") / ".venv") == Path("repo") / ".venv" / "bin" / "python"


def test_min_python_matches_baselode_requirement():
    assert RUN_SETUP.MIN_PYTHON == (3, 10)


def test_current_interpreter_is_probed_correctly():
    assert RUN_SETUP._interpreter_version([sys.executable]) == sys.version_info[:2]


def test_find_python_picks_newest_qualifying_candidate(monkeypatch):
    candidates = [("python3", ["/usr/bin/python3"]), ("python3.12", ["/opt/python3.12"]), ("python3.9", ["/usr/bin/python3.9"])]
    versions = {"/usr/bin/python3": (3, 11), "/opt/python3.12": (3, 12), "/usr/bin/python3.9": (3, 9)}
    monkeypatch.setattr(RUN_SETUP, "_candidate_commands", lambda: iter(candidates))
    monkeypatch.setattr(RUN_SETUP, "_interpreter_version", lambda cmd: versions[cmd[0]])
    assert RUN_SETUP._find_python(None) == ["/opt/python3.12"]


def test_find_python_refuses_when_everything_is_too_old(monkeypatch):
    monkeypatch.setattr(RUN_SETUP, "_candidate_commands", lambda: iter([("python3", ["/usr/bin/python3"])]))
    monkeypatch.setattr(RUN_SETUP, "_interpreter_version", lambda cmd: (3, 9))
    with pytest.raises(SystemExit) as excinfo:
        RUN_SETUP._find_python(None)
    message = str(excinfo.value)
    assert "No Python >= 3.10 found" in message
    assert "python3: Python 3.9 (too old)" in message


def test_explicit_python_below_minimum_is_rejected(monkeypatch):
    monkeypatch.setattr(RUN_SETUP.shutil, "which", lambda name: "/usr/bin/python3.9")
    monkeypatch.setattr(RUN_SETUP, "_interpreter_version", lambda cmd: (3, 9))
    with pytest.raises(SystemExit, match="needs Python >= 3.10"):
        RUN_SETUP._find_python("python3.9")


def test_explicit_launcher_form_is_split_into_a_command(monkeypatch):
    monkeypatch.setattr(RUN_SETUP.shutil, "which", lambda name: "C:\\Windows\\py.exe" if name == "py" else None)
    monkeypatch.setattr(RUN_SETUP, "_interpreter_version", lambda cmd: (3, 12))
    assert RUN_SETUP._find_python("py -3.12") == ["py", "-3.12"]


def test_explicit_path_with_spaces_is_not_split(monkeypatch, tmp_path):
    exe_dir = tmp_path / "Program Files" / "Python312"
    exe_dir.mkdir(parents=True)
    exe = exe_dir / "python.exe"
    exe.write_text("")
    monkeypatch.setattr(RUN_SETUP.shutil, "which", lambda name: None)
    monkeypatch.setattr(RUN_SETUP, "_interpreter_version", lambda cmd: (3, 12))
    assert RUN_SETUP._find_python(str(exe)) == [str(exe)]
