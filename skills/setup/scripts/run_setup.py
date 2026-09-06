#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Darkmine Pty Ltd
"""Bootstrap a fresh darkmine-data-skills checkout.

Creates a .venv, pip-installs ``baselode[all]`` plus ``kaleido`` from
PyPI, and (optionally) symlinks every skill into ~/.claude/skills/ or
a project's .claude/skills/ so Claude Code discovers them.

Works on macOS, Linux and Windows.  On Windows the venv interpreter
lives at ``.venv\\Scripts\\python.exe`` and, when symlinks aren't
permitted, skills are linked as directory junctions instead.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# baselode's `requires-python` (python/pyproject.toml in the baselode repo).
# Keep in sync when baselode changes it.
MIN_PYTHON = (3, 10)

# Newest first.  `python` (unversioned) is what Windows installs put on PATH;
# `py` is the Windows launcher and is probed separately below.
PYTHON_CANDIDATES = (
    "python3.13", "python3.12", "python3.11", "python3.10", "python3", "python",
)
PY_LAUNCHER_VERSIONS = ("3.13", "3.12", "3.11", "3.10")
WINDOWS = sys.platform == "win32"


def _venv_python(venv_dir):
    """Interpreter path inside *venv_dir* for the current platform."""
    if WINDOWS:
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _interpreter_version(cmd):
    """Return ``(major, minor)`` for the interpreter command *cmd*, or ``None``."""
    probe = "import sys; print(sys.version_info[0], sys.version_info[1])"
    try:
        result = subprocess.run(
            [*cmd, "-c", probe], capture_output=True, text=True, check=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    parts = result.stdout.split()
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        return None
    return int(parts[0]), int(parts[1])


def _candidate_commands():
    """Yield ``(label, cmd)`` for every interpreter we can find on this machine."""
    seen = set()
    for name in PYTHON_CANDIDATES:
        path = shutil.which(name)
        if not path:
            continue
        resolved = str(Path(path).resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        yield name, [path]
    if WINDOWS and shutil.which("py"):
        for version in PY_LAUNCHER_VERSIONS:
            yield f"py -{version}", ["py", f"-{version}"]


def _format_version(version):
    return ".".join(str(part) for part in version)


def _find_python(explicit):
    """Pick an interpreter command that satisfies :data:`MIN_PYTHON`.

    Returns a command list (``["/usr/bin/python3.12"]`` or ``["py", "-3.12"]``).
    """
    minimum = _format_version(MIN_PYTHON)
    if explicit:
        cmd = explicit.split() if " " in explicit else [explicit]
        if not shutil.which(cmd[0]) and not Path(cmd[0]).exists():
            raise SystemExit(f"--python {explicit!r} not found on PATH")
        version = _interpreter_version(cmd)
        if version is None:
            raise SystemExit(f"--python {explicit!r} could not be run to check its version")
        if version < MIN_PYTHON:
            raise SystemExit(
                f"--python {explicit!r} is Python {_format_version(version)}, but baselode "
                f"needs Python >= {minimum}.  Point --python at a newer interpreter."
            )
        return cmd

    found = []
    for label, cmd in _candidate_commands():
        version = _interpreter_version(cmd)
        if version is None:
            continue
        found.append((version, label, cmd))
    usable = [entry for entry in found if entry[0] >= MIN_PYTHON]
    if usable:
        usable.sort(key=lambda entry: entry[0], reverse=True)
        _, label, cmd = usable[0]
        print(f"[venv] using {label} (Python {_format_version(usable[0][0])})")
        return cmd

    lines = [f"No Python >= {minimum} found; baselode on PyPI requires it."]
    if found:
        lines.append("Interpreters on PATH:")
        for version, label, _ in sorted(found, key=lambda entry: entry[0], reverse=True):
            lines.append(f"  - {label}: Python {_format_version(version)} (too old)")
    else:
        lines.append(f"Searched: {', '.join(PYTHON_CANDIDATES)}" + (" and the `py` launcher." if WINDOWS else "."))
    lines.append(
        f"Install Python >= {minimum} (python.org, pyenv, or `uv python install 3.12`) "
        "and re-run, or pass --python PATH."
    )
    raise SystemExit("\n".join(lines))


def _run(cmd, **kwargs):
    print(f"  $ {' '.join(str(c) for c in cmd)}", flush=True)
    return subprocess.run(cmd, check=True, **kwargs)


def _create_venv(repo_dir, python_cmd):
    venv_dir = repo_dir / ".venv"
    venv_python = _venv_python(venv_dir)
    if venv_dir.exists() and venv_python.exists():
        print(f"[venv] reusing existing {venv_dir}")
        version = _interpreter_version([str(venv_python)])
        if version is not None and version < MIN_PYTHON:
            raise SystemExit(
                f"Existing {venv_dir} is Python {_format_version(version)}, but baselode needs "
                f">= {_format_version(MIN_PYTHON)}.  Delete the .venv directory and re-run."
            )
    else:
        print(f"[venv] creating {venv_dir} (python: {' '.join(python_cmd)})")
        _run([*python_cmd, "-m", "venv", str(venv_dir)])
        if not venv_python.exists():
            raise SystemExit(
                f"venv was created but no interpreter found at {venv_python}; "
                "check the venv layout for this platform."
            )
    _run([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"])
    return venv_python


def _install_baselode(venv_python, baselode_spec):
    print(f"[deps] pip install {baselode_spec} kaleido")
    try:
        _run([str(venv_python), "-m", "pip", "install", baselode_spec, "kaleido"])
    except subprocess.CalledProcessError as exc:
        version = _interpreter_version([str(venv_python)])
        version_text = _format_version(version) if version else "unknown"
        raise SystemExit(
            f"pip could not install {baselode_spec!r} into the venv (Python {version_text}).\n"
            f"baselode on PyPI needs Python >= {_format_version(MIN_PYTHON)}; if pip reported "
            "'No matching distribution', the venv interpreter is too old — delete .venv and "
            "re-run with --python pointing at a newer interpreter.  Otherwise see pip's output above."
        ) from exc


def _resolve_link_root(scope, project_dir):
    if scope == "user":
        return Path.home() / ".claude" / "skills"
    if scope == "project":
        if project_dir is None:
            raise SystemExit("--scope project requires --project-dir")
        return project_dir.resolve() / ".claude" / "skills"
    if scope == "none":
        return None
    raise SystemExit(f"Unknown --scope {scope!r}")


def _link_target(path):
    """Where *path* points if it is a symlink or Windows junction, else ``None``."""
    try:
        current = os.readlink(path)
    except (OSError, ValueError):
        return None
    if WINDOWS and current.startswith("\\\\?\\"):
        current = current[4:]
    return current


def _same_location(link_value, skill_dir):
    try:
        return Path(link_value).resolve() == skill_dir.resolve()
    except OSError:
        return link_value == str(skill_dir.resolve())


def _link_directory(target, source):
    """Symlink *target* -> *source*; fall back to a junction on Windows.

    Creating symlinks on Windows needs Developer Mode or elevation.  A
    directory junction needs neither and Claude Code follows it fine.
    """
    try:
        target.symlink_to(source, target_is_directory=True)
        return "symlink"
    except OSError:
        if not WINDOWS:
            raise
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(target), str(source)],
        check=True, capture_output=True, text=True,
    )
    return "junction"


def _symlink_skills(repo_dir, link_root):
    link_root.mkdir(parents=True, exist_ok=True)
    skills_dir = repo_dir / "skills"
    if not skills_dir.exists():
        raise SystemExit(f"Expected skills directory at {skills_dir}")
    created, kept, conflicts = [], [], []
    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        if not (skill_dir / "SKILL.md").exists():
            continue
        target = link_root / skill_dir.name
        current = _link_target(target)
        if current is not None:
            if _same_location(current, skill_dir):
                kept.append(skill_dir.name)
            else:
                conflicts.append((skill_dir.name, current))
            continue
        if target.exists():
            conflicts.append((skill_dir.name, "existing non-symlink path"))
            continue
        kind = _link_directory(target, skill_dir.resolve())
        created.append(skill_dir.name if kind == "symlink" else f"{skill_dir.name} (junction)")
    return created, kept, conflicts


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("repo_dir", type=Path,
                   help="Path to the darkmine-data-skills checkout.")
    p.add_argument("--scope", choices=("user", "project", "none"), default="user")
    p.add_argument("--project-dir", type=Path, default=None)
    p.add_argument("--python", default=None,
                   help="Python interpreter for the venv (default: newest of "
                        f"{', '.join(PYTHON_CANDIDATES)} that is >= "
                        f"{_format_version(MIN_PYTHON)}; on Windows the `py` launcher is "
                        "probed too).  Accepts a path or a launcher form like 'py -3.12'.")
    p.add_argument("--baselode-spec", default="baselode[all]",
                   help="Pip requirement for baselode (default: 'baselode[all]'). "
                        "Override to pin a version, install from git, or use a "
                        "local editable checkout, e.g. "
                        "'git+https://github.com/darkmine-oss/baselode.git@main#subdirectory=python' "
                        "or '-e ../baselode/python[all]'.")
    p.add_argument("--skip-venv", action="store_true")
    p.add_argument("--skip-link", action="store_true")
    args = p.parse_args(argv)

    repo_dir = args.repo_dir.resolve()
    if not (repo_dir / "skills").is_dir():
        p.error(f"REPO_DIR doesn't look like darkmine-data-skills: {repo_dir}")

    venv_dir = repo_dir / ".venv"
    if not args.skip_venv:
        python_cmd = _find_python(args.python)
        venv_python = _create_venv(repo_dir, python_cmd)
        _install_baselode(venv_python, args.baselode_spec)
    else:
        venv_python = _venv_python(venv_dir)

    created, kept, conflicts = [], [], []
    link_root = None
    if not args.skip_link:
        link_root = _resolve_link_root(args.scope, args.project_dir)
        if link_root is not None:
            print(f"[link] symlinking skills into {link_root}")
            created, kept, conflicts = _symlink_skills(repo_dir, link_root)

    print()
    print("=== Setup complete ===")
    if not args.skip_venv:
        print(f"  venv:          {venv_dir}")
        print(f"  python:        {venv_python}")
    if not args.skip_link and args.scope != "none":
        print(f"  scope:         {args.scope}")
        print(f"  link root:     {link_root}")
        if created:
            print(f"  created:       {', '.join(created)}")
        if kept:
            print(f"  already there: {', '.join(kept)}")
        if conflicts:
            print(f"  conflicts:     {len(conflicts)} — left untouched:")
            for name, where in conflicts:
                print(f"    - {name}: {where}")

    if not args.skip_link and args.scope != "none":
        print()
        print("Next: restart Claude Code (or start a new session).  "
              "Ask it 'which skills are available?' to confirm discovery.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
