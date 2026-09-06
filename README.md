# darkmine-data-skills

Reusable skills for AI agents (and humans on the CLI) that operate on **Baselode** drillhole + surface-sample data.

Each skill is a self-contained subdirectory under `skills/` with:

- `SKILL.md` — frontmatter (`name`, `description`) + when to use + invocation
- `scripts/` — the Python entry point(s)
- `agents/` (optional) — additional agent prompts

Each skill script just does `from baselode.drill.X import Y` — install [`baselode`](https://pypi.org/project/baselode/) into whichever Python environment you run them from.

## Setup

Two flavours — pick the one that fits.

### One-shot via the bootstrap skill (recommended)

The [`setup`](skills/setup/SKILL.md) skill does everything: create the venv, `pip install baselode[all] kaleido`, and symlink every skill into Claude Code's discovery directory.

```bash
git clone git@github.com:darkmine-oss/darkmine-data-skills.git
cd darkmine-data-skills
python3 skills/setup/scripts/run_setup.py "$PWD" --scope user
```

On Windows use `python` (or `py -3`) instead of `python3`; the script creates `.venv\Scripts\python.exe` and falls back to directory junctions when symlinks aren't permitted.

`--scope user` symlinks into `~/.claude/skills/` (every project sees them); `--scope project --project-dir /path/to/project` scopes them to a single project.

`baselode` needs **Python ≥ 3.10**.  The script picks the newest interpreter on `PATH` that qualifies and refuses older ones with a clear message — `pip`'s "No matching distribution found for baselode" is what you see when an old interpreter slips through.

Or once you've got *any* Claude Code session running in the cloned repo, just ask the agent: *"set this up for me"* — it'll pick up the `setup` skill and run the script for you.

### Manual

```bash
git clone git@github.com:darkmine-oss/darkmine-data-skills.git
cd darkmine-data-skills
python3.12 -m venv .venv
.venv/bin/pip install "baselode[all]" kaleido
```

The `[all]` extras pull in `lasio` (for `drillhole-las-import`) and `omf` (for `drillhole-omf-export`).  `kaleido` enables static PNG/SVG/PDF export from the strip-log and plan-section skills.

To run a skill directly from the CLI:

```bash
.venv/bin/python skills/drillhole-validate/scripts/validate_drillholes.py PROJECT_DIR
```

### Developing baselode alongside the skills

If you're hacking on `baselode` itself, install it editable from a local clone instead of PyPI:

```bash
git clone git@github.com:darkmine-oss/baselode.git ../baselode
.venv/bin/pip install -e "../baselode/python[all]" kaleido
```

…or pass `--baselode-spec '-e ../baselode/python[all]'` to the `setup` skill.

## Using these skills from Claude Code

Each skill is a standalone folder containing a `SKILL.md` (with `name` / `description` frontmatter) plus `scripts/`.  Claude Code auto-discovers skills under `~/.claude/skills/` (user-level) and `.claude/skills/` inside a project (project-level).  The [`setup`](skills/setup/SKILL.md) skill in the section above wires the symlinks up for you — re-running it on a fresh clone is the fastest path.

Once discovered, the natural-language phrases in each skill's frontmatter `description` field are what trigger it — e.g. *"find significant Au intercepts above 0.5 g/t over 5 m"* invokes `drillhole-intercepts`; *"export this to OMF"* invokes `drillhole-omf-export`.

To verify discovery, ask Claude `which skills are available?` — it should list every `drillhole-*` skill plus `gswa-drillsurface-to-baselode` and `setup`.

## Available skills

Grouped by what they do.

### Bootstrap

- [`setup`](skills/setup/SKILL.md) — Create a `.venv`, `pip install baselode[all] kaleido` from PyPI, and symlink every skill into `~/.claude/skills/` (or a project's `.claude/skills/`) so Claude Code discovers them.  Idempotent; safe to re-run.

### Ingest (raw data → Baselode project)

- [`gswa-drillsurface-to-baselode`](skills/gswa-drillsurface-to-baselode/SKILL.md) — Convert a GSWA Parquet dump (collars / surveys / assays / lithology / structure / drillhole alteration etc.) into a Baselode-shaped project folder with the standard `collars/survey/assays/geology/structure.parquet` tables.
- [`drillhole-las-import`](skills/drillhole-las-import/SKILL.md) — Read one `.las` file or a directory of LAS 1.2/2.0 files (via `lasio`) into a single concatenated `geophysics.parquet` keyed by `hole_id`/`depth`, one column per logged channel.

### Quality (find or fix problems)

- [`drillhole-validate`](skills/drillhole-validate/SKILL.md) — Full integrity sweep: orphan rows, gaps, overlaps, inverted intervals, survey rows with null azimuth/dip, holes with no usable survey station, single-station surveys, azimuth wraps, missing positions.  Produces a JSON + readable text report with fix recipes.
- [`drillhole-fix`](skills/drillhole-fix/SKILL.md) — Apply the automated fixes (`overlaps` — with optional `--prefer-dataset` campaign precedence — `inverted-intervals`, `orphan-intervals`, `unusable-survey-rows`, `synthesise-collar-station`, `normalize-azimuth`, `single-station-surveys`) non-destructively to a `fixed/` subfolder + a `fix_report.json` count.
- [`drillhole-interval-qa`](skills/drillhole-interval-qa/SKILL.md) — Lower-level interval ops as sub-commands: `gaps` / `overlaps` (diagnostics) and `split-at` / `clip` / `merge-tables` (mutations).

### Geometry (depth → 3D space)

- [`drillhole-desurvey`](skills/drillhole-desurvey/SKILL.md) — Collar + survey → `traces.parquet` with `easting/northing/elevation/md` per sample, using minimum-curvature (default), tangential, balanced-tangential, or Vulcan-style midpoint-tangential.  Every trace starts at the collar.
- [`drillhole-attach-positions`](skills/drillhole-attach-positions/SKILL.md) — Take any interval table and attach `easting/northing/elevation` by interpolating along the trace at each row's depth (anchor: `midpoint` / `from` / `to`).  Yields a points file ready for IDW or 3D plotting.

### Numerical (intervals → derived numbers)

- [`drillhole-composite`](skills/drillhole-composite/SKILL.md) — Length-weighted composites at a fixed downhole length, with soft or hard boundary modes (hard = reset at lithology/geology changes), and configurable residual handling.
- [`drillhole-composite-true-thickness`](skills/drillhole-composite-true-thickness/SKILL.md) — Same idea but the composites span a fixed amount of *true thickness* perpendicular to a reference plane (`--ref-dip` / `--ref-dip-azimuth`), so 1 m of true width means 1 m no matter the hole orientation.
- [`drillhole-intercepts`](skills/drillhole-intercepts/SKILL.md) — Significant-intercept extraction: contiguous runs above `--min-grade` with total length ≥ `--min-length`.  Writes one row per intercept with `from/to/length/avg_grade/label`.

### Structural

- [`drillhole-structural`](skills/drillhole-structural/SKILL.md) — Four transforms on `structure.parquet`: `attach-positions` (3D XYZ), `tadpole` (tadpole-log coords), `project-to-section`, `normalize-azimuth`.

### Visualisation (figures + interchange files)

- [`drillhole-strip-log`](skills/drillhole-strip-log/SKILL.md) — Single-hole strip log as HTML/PNG/SVG/PDF.  Modes: `categorical` (one label column → coloured bands), `geology` (Baselode's GSWA palette with `geology_code`/`comments` fallback), or `traces` (stacked numeric columns).
- [`drillhole-plan-section`](skills/drillhole-plan-section/SKILL.md) — 2D plan view (with optional `--depth-slice`) or vertical cross-section (`--origin` + `--azimuth` + `--width` corridor), rendered via Plotly.  Optional `--overlay-table` lays an interval table on top of the traces.
- [`drillhole-omf-export`](skills/drillhole-omf-export/SKILL.md) — Bundle collars (PointSet) + traces (LineSet) + selected interval tables (LineSets per table) into a single `.omf` file consumable by Leapfrog, Surpac, Vulcan plugins, etc.

## A typical pipeline

A representative chain that uses several skills together:

```text
gswa-drillsurface-to-baselode  →  drillhole-validate
                                  drillhole-fix              (if validate flags anything)
                                  drillhole-desurvey
                                  drillhole-composite        (or -true-thickness)
                                  drillhole-intercepts
                                  drillhole-omf-export       (or plan-section / strip-log
                                                              for a quick look)
```

Concretely on the CLI, after converting raw GSWA data:

```bash
# 1. Sanity-check the project before doing anything downstream.
python skills/drillhole-validate/scripts/validate_drillholes.py PROJECT_DIR

# 2. (If validate flagged issues) apply the automated fixes to a fixed/
#    subfolder and re-validate.  Add --prefer-dataset A,B when two sampling
#    campaigns overlap and one should win.
python skills/drillhole-fix/scripts/apply_fixes.py PROJECT_DIR --fix all

# 3. Build 3D traces so the frontend (and the IDW + true-thickness tools) can
#    read coordinates instead of recomputing them on the fly.
python skills/drillhole-desurvey/scripts/desurvey_holes.py PROJECT_DIR \
    --method minimum_curvature --step 1.0

# 4. Composite assays to 2 m, then again at 1 m true-thickness on the lode plane.
python skills/drillhole-composite/scripts/composite_intervals.py PROJECT_DIR \
    --value-col au_ppm --length 2.0
python skills/drillhole-composite-true-thickness/scripts/composite_true_thickness.py PROJECT_DIR \
    --value-field au_ppm --ref-dip 60 --ref-dip-azimuth 270 --length 1.0

# 5. Pull significant intercepts.
python skills/drillhole-intercepts/scripts/find_intercepts.py PROJECT_DIR \
    --assay-field au_ppm --min-grade 0.5 --min-length 2.0

# 6. Hand off to Leapfrog / Surpac.
python skills/drillhole-omf-export/scripts/export_omf.py PROJECT_DIR
```

Each script prints a one-line-per-step summary plus the output filenames.

## License

GPL-3.0-or-later.  See [LICENSE](LICENSE).
