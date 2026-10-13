# Copyright (C) 2026 Darkmine Pty Ltd.

"""Execute the validator's individual checks with explicit coverage records."""

from importlib.metadata import version
import math
import re

import pandas as pd
import baselode.drill.validate


def finite(value):
    try:
        return math.isfinite(float(value))
    except (ValueError, TypeError):
        return False


def numeric_mask(series):
    # Match the pinned engine's numeric coercion before it drops invalid rows.
    return pd.to_numeric(series, errors='coerce').map(finite).astype(bool)


def usable_ids(series):
    return (series.notna() & series.astype('string').str.strip().ne('').fillna(False)).astype(bool)


def validate(collar, survey, intervals, allow_full_circle=False):
    # Report row references are zero-based positions in each supplied table.
    # Keep source_row_index columns intact as separate raw provenance.
    collar = collar.reset_index(drop=True)
    survey = survey.reset_index(drop=True) if survey is not None else None
    intervals = {name: frame.reset_index(drop=True) for name, frame in intervals.items()}
    engine = baselode.drill.validate
    issues, checks = [], []
    engine_version = version('baselode')
    table_present = {'collar': True, 'survey': survey is not None,
                     **{name: name in intervals for name in ('assays', 'geology', 'structure')}}

    def run(check, name, frame, required, args, mask=None, reason=None, incomplete_on_missing=True):
        missing = [key for key in required if key not in frame]
        entry = {'check': check, 'table': name, 'engine': 'baselode.drill.validate',
                 'version': engine_version, 'required_columns': required, 'input_rows': len(frame),
                 'evaluated_rows': 0, 'excluded_rows': len(frame), 'evaluated_holes': 0,
                 'status': 'skipped', 'reason': reason, 'summary': {'error': 0, 'warning': 0, 'info': 0},
                 'options': {'allow_full_circle': allow_full_circle} if check == 'azimuth_range' else {}}
        checks.append(entry)
        if missing or frame.empty:
            entry['reason'] = 'Missing columns: ' + ', '.join(missing) if missing else (reason or 'No input rows')
            if missing and table_present[name] and incomplete_on_missing:
                entry['status'] = 'failed'
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
            if check == 'interval_overlaps':
                # Baselode 0.1.59 reports positions in the evaluated subset.
                # Translate both machine and human row references to input rows.
                for issue in found:
                    issue['row_index'] = int(selected.index[issue['row_index']])
                    issue['message'] = re.sub(
                        r'between rows (\d+)(?:\.0)? and (\d+)(?:\.0)?',
                        lambda match: f'between rows {selected.index[int(match[1])]} and {selected.index[int(match[2])]}',
                        issue['message'],
                    )
        except Exception as exc:
            entry.update(status='failed', reason=f'{type(exc).__name__}: {exc}')
            return
        for issue in found:
            entry['summary'][issue['severity']] += 1
        issues.extend(found)

    hole_mask = usable_ids(collar['hole_id']) if 'hole_id' in collar else None
    identified_collar = collar.loc[hole_mask] if hole_mask is not None else collar
    run('duplicate_hole_ids', 'collar', collar, ['hole_id'], (collar, 'hole_id'), hole_mask)
    def check_hole_ids(frame, name):
        if 'hole_id' not in frame:
            return
        missing_ids = ~usable_ids(frame['hole_id'])
        found = [{'check': 'missing_hole_id', 'severity': 'error', 'table': name,
                  'hole_id': None, 'row_index': int(position),
                  'message': 'Row has no usable hole ID', 'fix': None}
                 for position, missing in enumerate(missing_ids) if missing]
        issues.extend(found)
        checks.append({'check': 'missing_hole_id', 'table': name, 'engine': 'darkmine-data-skills',
                       'version': '0.1.3.dev0', 'status': 'executed', 'required_columns': ['hole_id'],
                       'input_rows': len(frame), 'evaluated_rows': len(frame), 'excluded_rows': 0,
                       'evaluated_holes': int(frame.loc[~missing_ids, 'hole_id'].nunique()),
                       'summary': {'error': len(found), 'warning': 0, 'info': 0},
                       'reason': None, 'options': {}})
    check_hole_ids(collar, 'collar')
    survey = survey if survey is not None else pd.DataFrame(columns=['hole_id', 'depth', 'azimuth', 'dip'])
    check_hole_ids(survey, 'survey')
    survey_ids = usable_ids(survey['hole_id']) if 'hole_id' in survey else pd.Series(False, index=survey.index)
    identified_survey = survey.loc[survey_ids]
    orientation = ['hole_id', 'depth', 'azimuth', 'dip']
    run('survey_null_orientation', 'survey', survey, orientation, (survey, *orientation))
    usable = pd.Series(True, index=survey.index)
    for key in orientation:
        usable &= usable_ids(survey[key]) if key == 'hole_id' and key in survey else numeric_mask(survey[key]) if key in survey else False
    if identified_survey.empty and 'hole_id' in collar and not collar.empty:
        # Older Baselode releases skip this check for an empty survey. The
        # umbrella reports those holes explicitly instead of silently passing.
        missing = identified_collar['hole_id'].unique()
        found = [{'check': 'survey_no_usable_stations', 'severity': 'warning', 'table': 'survey',
                  'hole_id': str(hole), 'row_index': None, 'message': 'Hole has no survey rows with a usable hole ID', 'fix': None} for hole in missing]
        issues.extend(found)
        checks.append({'check': 'survey_no_usable_stations', 'table': 'collar', 'engine': 'darkmine-data-skills',
                       'version': '0.1.3.dev0', 'status': 'executed' if hole_mask.all() else 'partial', 'required_columns': ['hole_id'],
                       'input_rows': len(collar), 'evaluated_rows': int(hole_mask.sum()), 'excluded_rows': int((~hole_mask).sum()),
                       'evaluated_holes': len(missing), 'summary': {'error': 0, 'warning': len(found), 'info': 0},
                       'reason': 'No survey rows with usable hole IDs', 'options': {}})
    else:
        run('survey_no_usable_stations', 'survey', survey, orientation,
            (identified_collar, identified_survey, *orientation), survey_ids,
            'Rows without usable hole IDs cannot form a survey group')
    run('single_station_surveys', 'survey', survey, orientation, (survey, *orientation), usable,
        'Only finite orientation/depth rows with a hole ID can form usable stations')
    for check, column in [('azimuth_range', 'azimuth'), ('dip_range', 'dip')]:
        args = (survey, 'hole_id', 'depth', column)
        if check == 'azimuth_range':
            args += (allow_full_circle,)
        run(check, 'survey', survey, ['hole_id', column], args,
            numeric_mask(survey[column]) if column in survey else None)
    ids = set(identified_collar['hole_id']) if 'hole_id' in collar else set()
    run('orphan_intervals', 'survey', survey, ['hole_id'], (survey, 'survey', ids, 'hole_id'), survey_ids,
        'Survey rows require a usable hole ID to check their parent collar')
    depths = engine._build_max_depth_lookup(identified_collar, 'hole_id', 'max_depth')
    for name in ('assays', 'geology', 'structure'):
        table = intervals.get(name, pd.DataFrame())
        check_hole_ids(table, name)
        absent_reason = 'Table absent or not represented by the conversion' if name not in intervals else 'No input rows' if table.empty else None
        known = usable_ids(table['hole_id']) if 'hole_id' in table else pd.Series(False, index=table.index)
        run('orphan_intervals', name, table, ['hole_id'], (table, name, ids, 'hole_id'), known, absent_reason)
        value_columns = [c for c in table if c not in {'hole_id', 'from', 'to', 'source_table', 'source_row_index'} and pd.api.types.is_string_dtype(table[c])]
        run('below_detection_limit', name, table, value_columns or ['<eligible string value column>'],
            (table.drop(columns=['source_table', 'source_row_index'], errors='ignore'), name, 'hole_id', 'from', 'to'),
            reason=absent_reason, incomplete_on_missing=False)
        if name == 'structure' and 'depth' in table and not {'from', 'to'}.intersection(table.columns):
            # Baselode structures are points. Interval checks are inapplicable,
            # not failed executions of a supported interval schema.
            reason = 'Point-model structure QAQC is outside interval-check coverage'
            for check in ('negative_lengths', 'intervals_beyond_max_depth', 'interval_gaps', 'interval_overlaps'):
                checks.append({'check': check, 'table': name, 'engine': 'baselode.drill.validate',
                               'version': engine_version, 'status': 'skipped', 'required_columns': ['hole_id', 'from', 'to'],
                               'input_rows': len(table), 'evaluated_rows': 0, 'excluded_rows': len(table),
                               'evaluated_holes': 0, 'summary': {'error': 0, 'warning': 0, 'info': 0},
                               'reason': reason, 'options': {}})
            if not table.empty:
                issues.append({'check': 'structure_coverage', 'severity': 'warning', 'table': name,
                               'hole_id': None, 'row_index': None, 'message': reason, 'fix': None})
                checks.append({'check': 'structure_coverage', 'table': name, 'engine': 'darkmine-data-skills',
                               'version': '0.1.3.dev0', 'status': 'executed', 'required_columns': ['depth'],
                               'input_rows': len(table), 'evaluated_rows': len(table), 'excluded_rows': 0,
                               'evaluated_holes': int(table['hole_id'].nunique()) if 'hole_id' in table else 0,
                               'summary': {'error': 0, 'warning': 1, 'info': 0}, 'reason': reason, 'options': {}})
            continue
        numeric = pd.Series(True, index=table.index)
        for column in ('from', 'to'):
            numeric &= numeric_mask(table[column]) if column in table else False
        if {'from', 'to'}.issubset(table.columns):
            found = [{'check': 'interval_invalid_bounds', 'severity': 'error', 'table': name,
                      'hole_id': None if 'hole_id' not in table or pd.isna(table.iloc[position]['hole_id'])
                          else str(table.iloc[position]['hole_id']),
                      'row_index': position, 'message': 'Interval has missing, non-numeric or non-finite bounds', 'fix': None}
                     for position, valid in enumerate(numeric) if not valid]
            issues.extend(found)
            checks.append({'check': 'interval_invalid_bounds', 'table': name, 'engine': 'darkmine-data-skills',
                           'version': '0.1.3.dev0', 'status': 'executed', 'required_columns': ['from', 'to'],
                           'input_rows': len(table), 'evaluated_rows': len(table), 'excluded_rows': 0,
                           'evaluated_holes': int(table['hole_id'].nunique()) if 'hole_id' in table else 0,
                           'summary': {'error': len(found), 'warning': 0, 'info': 0}, 'reason': None, 'options': {}})
        run('negative_lengths', name, table, ['from', 'to'], (table, name, 'hole_id', 'from', 'to'), numeric, absent_reason)
        depth_mask = known & table['hole_id'].isin(depths) & numeric_mask(table['to']) if {'hole_id', 'to'}.issubset(table.columns) else known & False
        run('intervals_beyond_max_depth', name, table, ['hole_id', 'to'], (table, name, depths, 'hole_id', 'to'), depth_mask,
            'Requires a usable interval end and matching collar maximum depth')
        for check in ('interval_gaps', 'interval_overlaps'):
            run(check, name, table, ['hole_id', 'from', 'to'], (table, name, 'hole_id', 'from', 'to'), numeric & known, absent_reason)
    return {'summary': {severity: sum(i['severity'] == severity for i in issues) for severity in ('error', 'warning', 'info')},
            'issues': issues, 'checks': checks, 'complete': not any(c['status'] == 'failed' for c in checks),
            'engine_version': engine_version, 'schema_version': 1}
