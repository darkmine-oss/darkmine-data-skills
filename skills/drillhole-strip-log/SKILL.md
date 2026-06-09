---
name: drillhole-strip-log
description: Render a downhole strip log for a single drillhole as a self-contained HTML (or PNG / SVG / PDF) figure — categorical bands (lithology, geology), numeric traces (assay grade), or both side-by-side. Wraps `baselode.drill.view.plot_strip_log`, `plot_geology_strip_log`, and `plot_drillhole_traces_subplots`. Use when a user asks to "draw a strip log for hole X", "plot lithology vs assays for this hole", or "make a strip log PDF".
version: v0.1.0
---

# Drillhole Strip Log

Produce a single-hole strip log.  Three modes:

| `--mode` | Source | Visual |
|---|---|---|
| `categorical` (default) | One interval table, one label column | Coloured bands |
| `geology` | `geology` table with `geology_code` and `comments` fallback | Coloured bands using Baselode's geology palette |
| `traces` | Two-or-more value columns from one interval table | Stacked numeric traces |

## Inputs

A Baselode project folder with at least one interval table.

## Command

```bash
python skills/drillhole-strip-log/scripts/plot_strip_log.py PROJECT_DIR \
    --hole-id RD0001 \
    [--mode categorical|geology|traces] \
    [--table assays] \
    [--label-col lithology] \
    [--value-cols au_ppm,cu_pct] \
    [--colour-map lithology] \
    [--output OUT.html] \
    [--format html|png|svg|pdf]
```

- `--hole-id` — required.
- `--mode` — default `categorical`.
- `--table` — interval table.  For `geology` mode default is `geology`; otherwise default is `assays`.
- `--label-col` — categorical column for `categorical` mode (default `lithology`).
- `--value-cols` — comma-separated numeric columns for `traces` mode.
- `--colour-map` — palette name (`commodity`, `lithology`) or omit for auto-cycle.
- `--output` — output file.  Default: `PROJECT_DIR/strip_logs/<hole_id>_<mode>.html`.
- `--format` — output format.  Inferred from `--output` suffix when given; otherwise `html`.  PNG / SVG / PDF require Kaleido (`pip install -U kaleido`).

## Outputs

A single Plotly figure exported to the chosen format.

## Notes For Agents

- Holes with no matching rows in the chosen table produce an empty figure — the script exits non-zero and prints a hint.
- For multiple holes, loop the script — each invocation writes one file.  This keeps each strip log a standalone artefact a geologist can email around.
- `geology` mode is wired up to Baselode's hard-coded GSWA palette and falls back to `comments` if `geology_code` is missing for a row.
