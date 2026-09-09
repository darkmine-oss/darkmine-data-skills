# Copyright (C) 2026 Darkmine Pty Ltd.

"""Execute the validator's individual checks with explicit coverage records."""

from importlib.metadata import version
import math

import pandas as pd
import baselode.drill.validate


def finite(value):
    try:
        return math.isfinite(float(value))
    except (ValueError, TypeError):
        return False


def validate(collar, survey, intervals, allow_full_circle=False):
    engine = baselode.drill.validate
    issues, checks = [], []
    engine_version = version('baselode')

    def run(check, name, frame, required, args, mask=None, reason=None):
        missing = [key for key in required if key not in frame]
        entry = {'check': check, 'table': name, 'engine': 'baselode.drill.validate',
                 'version': engine_version, 'required_columns': required, 'input_rows': len(frame),
                 'evaluated_rows': 0, 'excluded_rows': len(frame), 'evaluated_holes': 0,
                 'status': 'skipped', 'reason': reason, 'summary': {'error': 0, 'warning': 0, 'info': 0},
                 'options': {'allow_full_circle': allow_full_circle} if check == 'azimuth_range' else {}}
        checks.append(entry)
        if missing or frame.empty:
            entry['reason'] = 'Missing columns: ' + ', '.join(missing) if missing else (reason or 'No input rows')
            return
        selected = frame if mask is None else frame.loc[mask]
        entry.update(evaluated_rows=len(selected), excluded_rows=len(frame) - len(selected),
                     evaluated_holes=int(selected['hole_id'].nunique()) if 'hole_id' in selected else 0,
                     status='executed' if len(selected) == len(frame) else 'partial')
        if mask is not None and not mask.all():
            entry['reason'] = reason or 'Rows without usable check inputs were excluded'
        try:
            call_args = (selected, *args[1:]) if mask is not None and args[0] is frame else args
            found = getattr(engine, '_check_' + check)(*call_args)
        except Exception as exc:
            entry.update(status='failed', reason=f'{type(exc).__name__}: {exc}')
            return
        for issue in found:
            entry['summary'][issue['severity']] += 1
        issues.extend(found)

    hole_mask = collar['hole_id'].notna() if 'hole_id' in collar else None
    run('duplicate_hole_ids', 'collar', collar, ['hole_id'], (collar, 'hole_id'), hole_mask)
    survey = survey if survey is not None else pd.DataFrame(columns=['hole_id', 'depth', 'azimuth', 'dip'])
    orientation = ['hole_id', 'depth', 'azimuth', 'dip']
    run('survey_null_orientation', 'survey', survey, orientation, (survey, *orientation))
    usable = pd.Series(True, index=survey.index)
    for key in orientation:
        usable &= survey[key].notna() if key == 'hole_id' and key in survey else survey[key].map(finite) if key in survey else False
    if survey.empty and 'hole_id' in collar and not collar.empty:
        # Older Baselode releases skip this check for an empty survey. The
        # umbrella reports those holes explicitly instead of silently passing.
        missing = collar['hole_id'].dropna().unique()
        found = [{'check': 'survey_no_usable_stations', 'severity': 'warning', 'table': 'survey',
                  'hole_id': str(hole), 'row_index': None, 'message': 'Hole has no survey rows', 'fix': None} for hole in missing]
        issues.extend(found)
        checks.append({'check': 'survey_no_usable_stations', 'table': 'collar', 'engine': 'darkmine-data-skills',
                       'version': '0.1.0', 'status': 'executed' if collar['hole_id'].notna().all() else 'partial', 'required_columns': ['hole_id'],
                       'input_rows': len(collar), 'evaluated_rows': int(collar['hole_id'].notna().sum()), 'excluded_rows': int(collar['hole_id'].isna().sum()),
                       'evaluated_holes': len(missing), 'summary': {'error': 0, 'warning': len(found), 'info': 0},
                       'reason': 'Survey table absent or empty', 'options': {}})
    else:
        run('survey_no_usable_stations', 'survey', survey, orientation, (collar, survey, *orientation))
    run('single_station_surveys', 'survey', survey, orientation, (survey, *orientation), usable,
        'Only finite orientation/depth rows with a hole ID can form usable stations')
    for check, column in [('azimuth_range', 'azimuth'), ('dip_range', 'dip')]:
        args = (survey, 'hole_id', 'depth', column)
        if check == 'azimuth_range':
            args += (allow_full_circle,)
        run(check, 'survey', survey, ['hole_id', column], args,
            survey[column].map(finite) if column in survey else None)
    ids = set(collar['hole_id'].dropna()) if 'hole_id' in collar else set()
    depths = engine._build_max_depth_lookup(collar, 'hole_id', 'max_depth')
    for name in ('assays', 'geology', 'structure'):
        table = intervals.get(name, pd.DataFrame())
        absent_reason = 'Table absent or not represented by the conversion' if name not in intervals else 'No input rows' if table.empty else None
        known = table['hole_id'].notna() if 'hole_id' in table else pd.Series(False, index=table.index)
        numeric = pd.Series(True, index=table.index)
        for column in ('from', 'to'):
            numeric &= table[column].map(finite) if column in table else False
        run('orphan_intervals', name, table, ['hole_id'], (table, name, ids, 'hole_id'), known, absent_reason)
        run('negative_lengths', name, table, ['from', 'to'], (table, name, 'hole_id', 'from', 'to'), numeric, absent_reason)
        depth_mask = known & table['hole_id'].isin(depths) & table['to'].map(finite) if {'hole_id', 'to'}.issubset(table.columns) else known & False
        run('intervals_beyond_max_depth', name, table, ['hole_id', 'to'], (table, name, depths, 'hole_id', 'to'), depth_mask,
            'Requires a usable interval end and matching collar maximum depth')
        for check in ('interval_gaps', 'interval_overlaps'):
            run(check, name, table, ['hole_id', 'from', 'to'], (table, name, 'hole_id', 'from', 'to'), numeric & known, absent_reason)
        value_columns = [c for c in table if c not in {'hole_id', 'from', 'to', 'source_table', 'source_row_index'} and pd.api.types.is_string_dtype(table[c])]
        run('below_detection_limit', name, table, value_columns or ['<eligible string value column>'],
            (table.drop(columns=['source_table', 'source_row_index'], errors='ignore'), name, 'hole_id', 'from', 'to'), reason=absent_reason)
    return {'summary': {severity: sum(i['severity'] == severity for i in issues) for severity in ('error', 'warning', 'info')},
            'issues': issues, 'checks': checks, 'complete': not any(c['status'] == 'failed' for c in checks),
            'engine_version': engine_version, 'schema_version': 1}
