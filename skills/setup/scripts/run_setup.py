#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Darkmine Pty Ltd
"""Bootstrap a fresh darkmine-data-skills checkout.

Creates a .venv, pip-installs ``baselode[all]`` plus ``kaleido`` from
PyPI, and (optionally) symlinks every skill into ~/.claude/skills/ or
a project's .claude/skills/ so Claude Code discovers them.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

PYTHON_CANDIDATES = ("python3.12", "python3.11", "python3.10", "python3")


def _find_python(explicit):
    if explicit:
        if not shutil.which(explicit):
            raise SystemExit(f"--python {explicit!r} not found on PATH")
        return explicit
    for name in PYTHON_CANDIDATES:
        if shutil.which(name):
            return name
    raise SystemExit(
        "No suitable Python found.  Install Python ≥ 3.10 and re-run, "
        f"or pass --python.  Searched: {', '.join(PYTHON_CANDIDATES)}."
    )


def _run(cmd, **kwargs):
    print(f"  $ {' '.join(str(c) for c in cmd)}", flush=True)
    return subprocess.run(cmd, check=True, **kwargs)


def _create_venv(repo_dir, python_exec):
    venv_dir = repo_dir / ".venv"
    venv_python = venv_dir / "bin" / "python"
    if venv_dir.exists() and venv_python.exists():
        print(f"[venv] reusing existing {venv_dir}")
    else:
        print(f"[venv] creating {venv_dir} (python: {python_exec})")
        _run([python_exec, "-m", "venv", str(venv_dir)])
    _run([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"])
    return venv_python


def _install_baselode(venv_python, baselode_spec):
    print(f"[deps] pip install {baselode_spec} kaleido")
    _run([str(venv_python), "-m", "pip", "install", baselode_spec, "kaleido"])


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
        if target.is_symlink():
            current = os.readlink(target)
            if Path(current) == skill_dir.resolve() or current == str(skill_dir.resolve()):
                kept.append(skill_dir.name)
            else:
                conflicts.append((skill_dir.name, current))
            continue
        if target.exists():
            conflicts.append((skill_dir.name, "existing non-symlink path"))
            continue
        target.symlink_to(skill_dir.resolve(), target_is_directory=True)
        created.append(skill_dir.name)
    return created, kept, conflicts


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("repo_dir", type=Path,
                   help="Path to the darkmine-data-skills checkout.")
    p.add_argument("--scope", choices=("user", "project", "none"), default="user")
    p.add_argument("--project-dir", type=Path, default=None)
    p.add_argument("--python", default=None,
                   help="Python interpreter for the venv (default: best of "
                        f"{', '.join(PYTHON_CANDIDATES)})")
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

    if not args.skip_venv:
        python_exec = _find_python(args.python)
        venv_python = _create_venv(repo_dir, python_exec)
        _install_baselode(venv_python, args.baselode_spec)
    else:
        venv_python = repo_dir / ".venv" / "bin" / "python"

    created = kept = conflicts = []
    if not args.skip_link:
        link_root = _resolve_link_root(args.scope, args.project_dir)
        if link_root is not None:
            print(f"[link] symlinking skills into {link_root}")
            created, kept, conflicts = _symlink_skills(repo_dir, link_root)

    print()
    print("=== Setup complete ===")
    if not args.skip_venv:
        print(f"  venv:          {repo_dir}/.venv")
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
