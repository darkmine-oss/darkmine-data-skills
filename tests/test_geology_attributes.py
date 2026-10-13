# Copyright (C) 2026 Darkmine Pty Ltd.

import json
import pandas as pd
import pytest
from darkmine_data_skills.gswa import audit_conversion


def test_geology_flat_fields_extras_and_conflicts(tmp_path):
    raw=tmp_path/'raw';raw.mkdir()
    pd.DataFrame({'Id':[1], 'HoleId':['H']}).to_parquet(raw/'dbo_collar.parquet')
    pd.DataFrame({'Id':[10,11], 'CollarId':[1,1], 'FromDepth':[4.,3.], 'ToDepth':[2.,9.],
                  'MRTFileId':[8,9]}).to_parquet(raw/'dbo_dhgeology.parquet')
    pd.DataFrame({'Id':list(range(1,8)), 'DHGeologyId':[10]*7,
                  'AttributeColumn':['Lith1_Code','Lith1','Lith2_Code','Lith1_Colour1',
                                     'Lith1_Texture','Lith1_Structure','Rare_Field'],
                  'AttributeValue':['SSD','SSL','V','grey','massive','foliated',None],
                  'MRTDetailId':[100]*7}).to_parquet(raw/'dbo_dhgeologyattr.parquet')
    output=tmp_path/'output'
    manifest=audit_conversion.convert(raw,output)
    g=pd.read_parquet(output/'geology.parquet')
    assert len(g)==2
    assert g['from'].tolist()==[4.,3.]
    assert g['to'].tolist()==[2.,9.]
    assert g.loc[0,'lithology']=='SSD'
    assert g.loc[0,'geology_code']=='SSD'
    assert g.loc[0,'lithology_2']=='V'
    assert g.loc[0,'colour']=='grey'
    assert g.loc[0,'texture']=='massive'
    assert g.loc[0,'structure']=='foliated'
    extra=json.loads(g.loc[0,'attributes_extra'])
    assert extra['rare_field'] is None
    assert extra['_source_record']['MRTFileId']==8
    assert len(extra['_attribute_records'])==7
    assert extra['_conflicts']['lithology'][0]['selected'] is True
    assert g.loc[0,'attribute_clash_count']==1
    assert g.loc[1,'attribute_clash_count']==0
    assert manifest['sources']['dbo_dhgeologyattr']['converted_to']==['geology']
    assert manifest['tables']['geology']['joined_source_coverage']['dbo_dhgeologyattr']['retained_attribute_records']==7
    assert not (output/'.conversion-incomplete').exists()
    assert not (output/'geology_attributes.parquet').exists()


def test_orphan_geology_attributes_fail_without_success_manifest(tmp_path):
    raw=tmp_path/'raw';raw.mkdir()
    pd.DataFrame({'Id':[1],'HoleId':['H']}).to_parquet(raw/'dbo_collar.parquet')
    pd.DataFrame({'Id':[10],'CollarId':[1],'FromDepth':[0.],'ToDepth':[1.]}).to_parquet(raw/'dbo_dhgeology.parquet')
    pd.DataFrame({'Id':[1],'DHGeologyId':[999],'AttributeColumn':['Lith1'],'AttributeValue':['A']}).to_parquet(raw/'dbo_dhgeologyattr.parquet')
    out=tmp_path/'out'
    with pytest.raises(ValueError,match='orphan'):
        audit_conversion.convert(raw,out)
    assert (out/'.conversion-incomplete').exists()
    assert not (out/'conversion_manifest.json').exists()


def test_legacy_aliases_and_parent_float_precision(tmp_path):
    raw=tmp_path/'raw';raw.mkdir()
    pd.DataFrame({'Id':[1],'HoleId':['H']}).to_parquet(raw/'dbo_collar.parquet')
    boundary=0.123456789012345
    pd.DataFrame({'Id':[10],'CollarId':[1],'FromDepth':[boundary],'ToDepth':[1.]}).to_parquet(raw/'dbo_dhgeology.parquet')
    pd.DataFrame({'Id':[1,2,3], 'DHGeologyId':[10,10,10],
                  'AttributeColumn':['Lith Code 1','Lith Code 2','Lithology Description'],
                  'AttributeValue':['A','B','Original description']}).to_parquet(raw/'dbo_dhgeologyattr.parquet')
    output=tmp_path/'out'
    audit_conversion.convert(raw,output)
    g=pd.read_parquet(output/'geology.parquet')
    assert g.loc[0,'lithology']=='A'
    assert g.loc[0,'lithology_2']=='B'
    assert g.loc[0,'comments']=='Original description'
    assert json.loads(g.loc[0,'attributes_extra'])['_source_record']['FromDepth']==boundary
