---
name: drillhole-las-import
description: Import downhole geophysics LAS 1.2 / 2.0 files into a Baselode-compatible Parquet table — one Parquet per LAS, or one concatenated table for many holes. Wraps `baselode.drill.las.load_geophysics_las`. Use when a user asks to "load LAS logs", "import the geophysics", "convert the LAS folder to Parquet", or "combine these gamma logs into one table".
version: v0.1.0
---

# Drillhole LAS Import

Read one or many LAS files (LAS 1.2 / 2.0) into pandas via `lasio` and write them out as Parquet (or CSV) under the project folder.  The output columns are `hole_id`, `depth`, plus one column per logged channel (gamma, density, resistivity, …).

## Inputs

Either:
- A single `.las` file, **or**
- A directory of `.las` files (recursive optional).

Plus the destination Baselode project folder.

## Command

```bash
python skills/drillhole-las-import/scripts/import_las.py PROJECT_DIR \
    --source PATH_TO_FILE_OR_DIR \
    [--hole-id HOLE_ID] \
    [--recursive] \
    [--null-sentinel -999.25] \
    [--output-name geophysics] \
    [--format parquet|csv]
```

- `--source` — `.las` file or directory.
- `--hole-id` — override the hole id (single-file mode only; otherwise read from the LAS `~WELL` block).
- `--recursive` — recurse into subdirectories when `--source` is a folder.
- `--null-sentinel` — value to coerce to NaN (default: read from each LAS, fallback `-999.25`).
- `--output-name` — output stem under `PROJECT_DIR/` (default `geophysics`).
- `--format` — `parquet` (default, with snappy compression) or `csv`.

## Outputs

A single concatenated table written to `PROJECT_DIR/<output-name>.<format>` with columns:

| Column | Meaning |
|---|---|
| `hole_id` | Hole identifier (from LAS `~WELL` or `--hole-id`) |
| `depth` | Downhole depth (m) |
| `<channel>` | One column per logged curve (lowercased mnemonic) |

## Notes For Agents

- Requires `lasio`.  Install with `pip install lasio` (or `pip install "baselode[las]"`).
- LAS files for different holes can have **different curve sets** — the concatenated table simply contains NaN where a hole didn't log a channel.
- After import, `drillhole-attach-positions` against `--table geophysics` (anchored at depth-as-from/to interval) gives 3D XYZ for every log sample.
