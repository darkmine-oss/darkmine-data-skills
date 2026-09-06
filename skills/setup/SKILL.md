---
name: setup
description: Bootstrap a freshly cloned darkmine-data-skills checkout — create a `.venv`, pip-install `baselode[all]` plus `kaleido` from PyPI, and symlink every sibling skill into either a project's `.claude/skills/` or the user-level `~/.claude/skills/` so Claude Code discovers them. Use when a user says "set this up", "get me bootstrapped", "wire these skills into Claude Code", or is staring at a fresh clone wondering what to do next.
version: v0.1.0
---

# Setup

One-shot bootstrap for a fresh `darkmine-data-skills` checkout.  Does three things:

1. Creates `darkmine-data-skills/.venv` using the newest Python ≥ 3.10 it can find (baselode's `requires-python`).  Every candidate is version-checked *before* the venv is created, so an old interpreter fails fast with a clear message instead of dying inside `pip install`.
2. `pip install baselode[all] kaleido` — the `[all]` extra pulls in folium, sqlalchemy, lasio, requests, omf; `kaleido` is for static image export.
3. Symlinks every sibling skill (including itself) into either:
   - a target project's `.claude/skills/` (per-project scope), or
   - the user-level `~/.claude/skills/` (every project).

Idempotent — re-running upgrades pip + dependencies and leaves existing symlinks in place.

## Inputs

Just the path to a `darkmine-data-skills` checkout, plus whichever scope you want for Claude Code discovery.

## Command

```bash
python skills/setup/scripts/run_setup.py REPO_DIR \
    [--scope user|project|none] \
    [--project-dir PATH] \
    [--python PYTHON_EXEC] \
    [--baselode-spec SPEC] \
    [--skip-venv] \
    [--skip-link]
```

- `REPO_DIR` — path to the `darkmine-data-skills` checkout itself.
- `--scope` — where to expose the skills to Claude Code.  Default `user`.
  - `user` → `~/.claude/skills/<skill>/`
  - `project` → `<project-dir>/.claude/skills/<skill>/` (requires `--project-dir`)
  - `none` → only set up the venv, no symlinks
- `--project-dir` — required when `--scope project`.
- `--python` — interpreter to use for the venv (default: newest of `python3.13`, `python3.12`, `python3.11`, `python3.10`, `python3`, `python` on `PATH` that is ≥ 3.10; on Windows the `py` launcher is probed as well).  Accepts a path or a launcher form such as `"py -3.12"`.
- `--baselode-spec` — pip requirement for baselode (default `baselode[all]`).  Override to pin a version, install from git, or use a local editable checkout — e.g. `git+https://github.com/darkmine-oss/baselode.git@main#subdirectory=python` or `-e ../baselode/python[all]`.
- `--skip-venv` — only do the symlinks.
- `--skip-link` — only do the venv.

## Outputs

- `REPO_DIR/.venv/` with `baselode` + extras installed.  The interpreter is `.venv/bin/python` on macOS / Linux and `.venv\Scripts\python.exe` on Windows — the script picks the right one and prints it in the summary.
- Symlinks named after each skill in the chosen scope directory.
- A short summary printed to stdout (Python version, packages installed, symlinks created).

## Notes For Agents

- **This skill bootstraps the others.**  Until it has run once, `~/.claude/skills/` may be empty and Claude Code won't auto-discover the rest of the skills.  Tell the user: clone the repo, then either run this skill's script directly or symlink just this one skill in by hand to get the discovery loop started.
- Existing symlinks with the same name are kept untouched.  If a symlink points somewhere unexpected, the script warns but doesn't overwrite — let the user investigate.
- For per-project scope, the project's `.gitignore` should ignore `.claude/` (most templates already do).
- **Windows:** symlinks need Developer Mode or an elevated shell.  When `symlink_to` is refused the script falls back to a directory junction (`mklink /J`), which needs no privileges and which Claude Code follows just the same; the summary marks those entries `(junction)`.
- **"No matching distribution found for baselode"** from pip means the interpreter is older than baselode's `requires-python` (≥ 3.10).  The script now catches this up front; if you see it anyway, delete `.venv` and re-run with `--python` pointing at a newer interpreter.
