# Copyright (C) 2026 Darkmine Pty Ltd.

import json

import pandas as pd
import baselode.drill.validate

from darkmine_data_skills.gswa import audit_conversion
from darkmine_data_skills.validation import check_coverage, validate_drillholes


def test_conversion_preserves_duplicates_bad_orientation_and_overlap(tmp_path):
    raw, converted, report_dir = tmp_path / 'raw', tmp_path / 'baselode', tmp_path / 'qa'
    raw.mkdir()
    pd.DataFrame({'Id':[1,2], 'HoleId':['A','A'], 'CompanyHoleId':['Shown','Shown'], 'Latitude':[-30.,-30.], 'Longitude':[120.,120.], 'MaxDepth':[10.,10.]}).to_parquet(raw / 'dbo_collar.parquet')
    pd.DataFrame({'CollarId':[1,1], 'Depth':['0','5'], 'Azimuth':['360','bad'], 'Dip':['-90','-90']}).to_parquet(raw / 'dbo_dhsurvey.parquet')
    pd.DataFrame({'Id':[1,2], 'CollarId':[1,1], 'FromDepth':[0.,4.], 'ToDepth':[5.,12.]}).to_parquet(raw / 'dbo_dhgeology.parquet')
    pd.DataFrame({'Id':[4], 'Anything':['kept raw']}).to_parquet(raw / 'dbo_unmapped.parquet')
    manifest = audit_conversion.convert(raw, converted)
    assert len(pd.read_parquet(converted / 'collars.parquet')) == 2
    assert pd.read_parquet(converted / 'geology.parquet')['from'].tolist() == [0.,4.]
    assert 'dbo_unmapped' in manifest['not_converted']
    assert validate_drillholes.main([str(converted), str(report_dir), '--no-print-summary']) == 1
    report = json.loads((report_dir / 'drillhole_validation_report.json').read_text())
    checks = {i['check'] for i in report['issues']}
    assert {'duplicate_hole_ids','azimuth_range','survey_null_orientation','interval_overlaps','intervals_beyond_max_depth'} <= checks
    assert any(c['check'] == 'dip_range' and c['summary']['error'] == 0 for c in report['checks'])
    assert all(c['status'] == 'skipped' for c in report['checks'] if c['table'] == 'structure')


def test_missing_survey_is_not_a_clean_pass():
    result = check_coverage.validate(pd.DataFrame({'hole_id':['A']}), None, {})
    assert result['summary']['warning'] == 1
    assert any(c['check'] == 'survey_no_usable_stations' and c['status'] == 'executed' for c in result['checks'])
    assert any(c['check'] == 'azimuth_range' and c['status'] == 'skipped' for c in result['checks'])


def test_partial_depth_coverage_and_full_circle_option():
    collar = pd.DataFrame({'hole_id':['A','B'], 'max_depth':[5,None]})
    survey = pd.DataFrame({'hole_id':['A'], 'depth':[0], 'azimuth':[360], 'dip':[-90]})
    intervals = {'assays':pd.DataFrame({'hole_id':['A','B'], 'from':[0,0], 'to':[10,10], 'au_ppm':['<0.1','1']})}
    report = check_coverage.validate(collar,survey,intervals,allow_full_circle=True)
    assert not any(i['check'] == 'azimuth_range' for i in report['issues'])
    depth = next(c for c in report['checks'] if c['check']=='intervals_beyond_max_depth' and c['table']=='assays')
    assert (depth['status'],depth['evaluated_rows'],depth['excluded_rows']) == ('partial',1,1)
    assert any(i['check']=='below_detection_limit' for i in report['issues'])


def test_nonfinite_rows_are_excluded_from_range_but_reported_by_orientation():
    collar = pd.DataFrame({'hole_id':['A']})
    survey = pd.DataFrame({'hole_id':['A','A'], 'depth':[0,1], 'azimuth':[360,float('inf')], 'dip':[-90,-90]})
    result = check_coverage.validate(collar,survey,{})
    azimuth = next(c for c in result['checks'] if c['check']=='azimuth_range')
    assert (azimuth['evaluated_rows'],azimuth['excluded_rows']) == (1,1)
    assert azimuth['summary']['error']==1
    assert any(i['check']=='survey_null_orientation' and i['row_index']==1 for i in result['issues'])


def test_failed_check_is_recorded_and_other_checks_continue(monkeypatch):
    def broken(*args):
        raise RuntimeError('fixture check failure')
    monkeypatch.setattr(baselode.drill.validate, '_check_azimuth_range', broken)
    survey = pd.DataFrame({'hole_id':['A'], 'depth':[0], 'azimuth':[360], 'dip':[-100]})
    result = check_coverage.validate(pd.DataFrame({'hole_id':['A']}), survey, {})
    assert result['complete'] is False
    assert next(c for c in result['checks'] if c['check']=='azimuth_range')['status']=='failed'
    assert any(i['check']=='dip_range' for i in result['issues'])
