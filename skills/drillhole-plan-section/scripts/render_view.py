#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Darkmine Pty Ltd
"""Project drillhole traces to a plan or section frame and render via Plotly."""

import argparse
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
from baselode.drill.desurvey import (
    attach_assay_positions,
    minimum_curvature_desurvey,
)
from baselode.drill.view_2d import plan_view, section_view

EXTENSIONS_BY_PRIORITY = ("parquet", "csv")


def _read_table(project_dir, stem):
    for ext in EXTENSIONS_BY_PRIORITY:
        path = project_dir / f"{stem}.{ext}"
        if path.exists():
            return (pd.read_parquet(path) if ext == "parquet" else pd.read_csv(path)), ext
    return None, None


def _resolve_traces(project_dir):
    traces, _ = _read_table(project_dir, "traces")
    if traces is not None:
        return traces
    collars, _ = _read_table(project_dir, "collars")
    survey, _ = _read_table(project_dir, "survey")
    if collars is None or survey is None:
        raise SystemExit("Missing traces and missing collars/survey — cannot build a view.")
    return minimum_curvature_desurvey(collars, survey)


def _ensure_z(traces):
    df = traces.copy()
    if "z" not in df.columns and "elevation" in df.columns:
        df["z"] = df["elevation"]
    return df


def _parse_pair(value):
    parts = [float(x.strip()) for x in value.split(",")]
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(f"expected two comma-separated numbers, got {value!r}")
    return tuple(parts)


def _write_figure(fig, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower().lstrip(".")
    if suffix in ("html", ""):
        fig.write_html(str(path), include_plotlyjs="cdn")
    else:
        fig.write_image(str(path), format=suffix)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("project_dir", type=Path)
    sub = p.add_subparsers(dest="mode", required=True)

    plan = sub.add_parser("plan")
    plan.add_argument("--depth-slice", type=_parse_pair, default=None,
                      help="TOP,BOTTOM (z bounds, in elevation)")
    plan.add_argument("--colour-by", default=None)
    plan.add_argument("--overlay-table", default=None)
    plan.add_argument("--output", type=Path, default=None)

    sec = sub.add_parser("section")
    sec.add_argument("--origin", type=_parse_pair, required=True,
                     help="EASTING,NORTHING")
    sec.add_argument("--azimuth", type=float, required=True)
    sec.add_argument("--width", type=float, default=50.0)
    sec.add_argument("--colour-by", default=None)
    sec.add_argument("--overlay-table", default=None)
    sec.add_argument("--output", type=Path, default=None)

    args = p.parse_args(argv)
    project_dir = args.project_dir.resolve()
    if not project_dir.is_dir():
        p.error(f"PROJECT_DIR not a directory: {project_dir}")

    traces = _ensure_z(_resolve_traces(project_dir))

    overlay = None
    if args.overlay_table:
        overlay_df, _ = _read_table(project_dir, args.overlay_table)
        if overlay_df is None:
            p.error(f"Could not find {args.overlay_table}.{{parquet,csv}} in {project_dir}")
        overlay = _ensure_z(attach_assay_positions(overlay_df, traces))

    if args.mode == "plan":
        trace_proj = plan_view(traces, depth_slice=args.depth_slice, color_by=args.colour_by)
        if overlay is not None:
            overlay = plan_view(overlay, depth_slice=args.depth_slice, color_by=args.colour_by)
        fig = px.scatter(
            trace_proj, x="easting", y="northing",
            color="color_value" if "color_value" in trace_proj.columns else None,
            hover_data=["hole_id", "z"] if "hole_id" in trace_proj.columns else None,
            title="Plan view",
        )
        if overlay is not None and not overlay.empty:
            fig.add_scatter(
                x=overlay["easting"], y=overlay["northing"], mode="markers",
                name=f"{args.overlay_table}",
                marker=dict(size=4, opacity=0.6),
            )
        fig.update_yaxes(scaleanchor="x", scaleratio=1)
        default_out = project_dir / "views" / "plan.html"
    else:
        trace_proj = section_view(
            traces, origin=args.origin, azimuth=args.azimuth,
            width=args.width, color_by=args.colour_by,
        )
        if overlay is not None:
            overlay = section_view(
                overlay, origin=args.origin, azimuth=args.azimuth,
                width=args.width, color_by=args.colour_by,
            )
        fig = px.scatter(
            trace_proj, x="along", y="z",
            color="color_value" if "color_value" in trace_proj.columns else None,
            hover_data=["hole_id", "across"] if "hole_id" in trace_proj.columns else None,
            title=f"Section az={args.azimuth}° width={args.width} m",
        )
        if overlay is not None and not overlay.empty:
            fig.add_scatter(
                x=overlay["along"], y=overlay["z"], mode="markers",
                name=f"{args.overlay_table}",
                marker=dict(size=4, opacity=0.6),
            )
        fig.update_yaxes(scaleanchor="x", scaleratio=1)
        default_out = project_dir / "views" / f"section_az{int(args.azimuth)}.html"

    out = (args.output or default_out).resolve()
    _write_figure(fig, out)

    rel = out.relative_to(project_dir) if out.is_relative_to(project_dir) else out
    print(f"Mode: {args.mode}")
    print(f"Traces: {trace_proj['hole_id'].nunique() if 'hole_id' in trace_proj.columns else '?'} holes, {len(trace_proj):,} samples plotted")
    if overlay is not None:
        print(f"Overlay ({args.overlay_table}): {len(overlay):,} rows")
    print(f"Wrote: {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
