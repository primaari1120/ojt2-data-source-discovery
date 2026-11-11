"""Regression for Analyze durations and saved reviews; uses temporary SQLite only.

python 40_validate_analysis_runtime.py
python 40_validate_analysis_runtime.py --ui
"""
from __future__ import annotations
import argparse
from contextlib import closing
from datetime import datetime, timezone, timedelta
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ojt2_analysis_runtime import (AnalysisTimer, runtime_for_context, history_runtime,
                                   normalize_runtime, format_duration)

ROOT = Path(__file__).resolve().parent
REQ = {'purpose': 'Example request', 'source_hint': 'Example', 'required_fields': ['Id']}
SCOPE = ['DEMO_Example']


def measured():
    ticks = iter([100.0, 107.25])
    # Wall-clock adjustment cannot change a monotonic measured duration.
    walls = iter([datetime(2026, 11, 11, 10, tzinfo=timezone.utc),
                  datetime(2026, 11, 11, 9, tzinfo=timezone.utc)])
    timer = AnalysisTimer(REQ, SCOPE, 1, clock=lambda: next(ticks), now=lambda: next(walls))
    runtime = timer.finish()
    assert runtime['duration_seconds'] == 7.25 and normalize_runtime(runtime)
    assert timer.finish() == runtime  # no extra clock read / no human-review time
    copy = timer.finish();copy['duration_seconds'] = 1234
    assert timer.finish()['duration_seconds'] == 7.25
    assert format_duration(runtime) == '7.25 s'
    assert runtime_for_context(runtime, REQ, SCOPE, 1)
    assert not runtime_for_context(runtime, dict(REQ, purpose='Changed'), SCOPE, 1)
    assert not runtime_for_context(runtime, REQ, ['DEMO_Other'], 1)
    assert not runtime_for_context(runtime, REQ, SCOPE, 2)
    for bad in [-1, float('nan'), float('inf'), True, '7.25', None]:
        assert normalize_runtime(dict(runtime, duration_seconds=bad)) is None
    assert normalize_runtime(dict(runtime, started_at_utc='invalid')) is None
    assert normalize_runtime(dict(runtime, run_id='invalid')) is None
    assert history_runtime({'score_json': '{bad'}) is None
    assert format_duration(None) == '—'
    zero = dict(runtime, duration_seconds=0.0)
    assert normalize_runtime(zero) and format_duration(zero) == '0.00 s'
    return runtime


def persistence(temp, runtime):
    import ojt2_discovery_core as core
    path = temp/'history.sqlite'
    candidate = {'object_key': 'example-key', 'object': {'database_name': 'DEMO_Example',
                 'schema_name': 'dbo', 'object_name': 'Output'}, 'total': 1, 'matched': 1,
                 'score': 90.0, 'field_map': [], 'confidence_label': 'test'}
    old_id = core.save_review(REQ, candidate, [], 'PIC', 'Old review', SCOPE, 1, path=path)
    old = next(r for r in core.list_reviews(path=path) if r['id'] == old_id)
    with closing(sqlite3.connect(path)) as cn:
        schema_before = cn.execute('PRAGMA table_info(mapping_history)').fetchall()
    new_id = core.save_review(REQ, dict(candidate, analysis_runtime=runtime), [], 'PIC', 'New review', SCOPE, 1, path=path)
    rows = {r['id']:r for r in core.list_reviews(path=path)}
    assert rows[old_id] == old and history_runtime(old) is None
    stored = history_runtime(rows[new_id]);assert stored and stored['duration_seconds'] == 7.25
    assert stored['run_id'] == runtime['run_id']
    assert json.loads(rows[new_id]['score_json'])['analysis_runtime'] == stored
    for req, scope, revision in [(dict(REQ, purpose='Another'), SCOPE, 1), (REQ, ['DEMO_Other'], 1), (REQ, SCOPE, 2)]:
        key = core.save_review(req, dict(candidate, analysis_runtime=runtime), [], 'PIC', 'Mismatched context', scope, revision, path=path)
        assert history_runtime(next(r for r in core.list_reviews(path=path) if r['id'] == key)) is None
    with closing(sqlite3.connect(path)) as cn:
        assert cn.execute('PRAGMA table_info(mapping_history)').fetchall() == schema_before
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    core.list_reviews(path=path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    path.unlink()  # verifies the connection is not retained on Windows
    print('PASS: monotonic/frozen runtime, strict context binding, old/new records, no schema migration, connection closure.')


def ui_tests():
    from streamlit.testing.v1 import AppTest
    # Deterministic work stages prove elapsed time includes planning + discovery + support.
    setup = '''
import streamlit as st
import importlib.util
from pathlib import Path
from ojt2_analysis_runtime import AnalysisTimer,context_key
root=Path(ROOT_PATH)
spec=importlib.util.spec_from_file_location('runtime_ui_test',root/'15_adaptive_workflow_streamlit.py')
ui=importlib.util.module_from_spec(spec);spec.loader.exec_module(ui)
if 'clock_value' not in st.session_state: st.session_state['clock_value']=100.0
if 'events' not in st.session_state: st.session_state['events']=[]
def tick(amount,event):
 st.session_state['clock_value']+=amount;st.session_state['events'].append(event)
class Timer(AnalysisTimer):
 def __init__(self,*args,**kwargs):
  super().__init__(*args,**kwargs,clock=lambda:st.session_state['clock_value'])
ui.AnalysisTimer=Timer
req={'purpose':'Example request','source_hint':'Example','required_fields':['Id']}
data={'objects':[{'database_name':'DEMO_Example'}],'metadata_run':{'run_id':1}}
def plan(context):
 tick(1.0,'plan');return {'primary':'VALID'}
def discover(*args,**kwargs):
 tick(2.5,'discovery')
 return [{'object_key':'a','field_map':[]},{'object_key':'b','field_map':[]}] if not EMPTY else []
def support(*args,**kwargs):
 tick(3.5,'support');return []
ui.plan_search=plan;ui.discover=discover;ui.find_supporting=support
if RUN:
 ui._run_discovery(data,{},req,['DEMO_Example'],12)
else:
 st.caption('idle rerender')
'''
    def app(run=True, empty=False):
        return AppTest.from_string('ROOT_PATH='+repr(str(ROOT))+'\nRUN='+repr(run)+'\nEMPTY='+repr(empty)+'\n'+setup, default_timeout=20)
    a = app().run();assert not a.exception,[e.value for e in a.exception]
    first = a.session_state['analysis_runtime']
    assert first['duration_seconds'] == 7.0
    assert a.session_state['events'] == ['plan','discovery','support']
    assert all(c['analysis_runtime']['run_id'] == first['run_id'] for c in a.session_state['discovery_results'])
    a.run();assert not a.exception
    second = a.session_state['analysis_runtime']
    assert second['run_id'] != first['run_id'] and second['duration_seconds'] == 3.5
    assert a.session_state['events'].count('support') == 1, 'Existing supporting-source cache was not reused'
    empty = app(empty=True).run();assert not empty.exception
    assert empty.session_state['analysis_runtime']['status'] == 'no_candidates'
    assert empty.session_state['analysis_runtime']['duration_seconds'] == 3.5
    # A failure must not reuse results or timing from the previous successful run.
    broken = AppTest.from_string('ROOT_PATH='+repr(str(ROOT))+'\nRUN=False\nEMPTY=False\n'+setup+'''
def fail(*args,**kwargs):raise ValueError('test discovery failure')
ui.discover=fail
try:ui._run_discovery(data,{},req,['DEMO_Example'],12)
except ValueError:pass
''',default_timeout=20).run()
    assert not broken.exception
    assert broken.session_state['analysis_runtime']['status'] == 'failed'
    assert broken.session_state['discovery_results'] == []
    settings_failure = AppTest.from_string('ROOT_PATH='+repr(str(ROOT))+'\nRUN=False\nEMPTY=False\n'+setup+'''
st.session_state['analysis_runtime']={'duration_seconds':9999}
def fail_settings(*args,**kwargs):raise RuntimeError('test settings failure')
ui.get_setting=fail_settings
try:ui._run_discovery(data,{},req,['DEMO_Example'])
except RuntimeError:pass
''',default_timeout=20).run()
    assert not settings_failure.exception
    assert settings_failure.session_state['analysis_runtime']['status'] == 'failed'
    assert settings_failure.session_state['analysis_runtime']['duration_seconds'] == 1.0
    # Actual History page can mix a legacy row and a timed row without an ID error.
    history_code = '''
import importlib.util
from pathlib import Path
from datetime import datetime,timezone
from ojt2_analysis_runtime import AnalysisTimer
import ojt2_discovery_core as core
import streamlit as st
spec=importlib.util.spec_from_file_location('runtime_history_ui',Path(ROOT_PATH)/'15_adaptive_workflow_streamlit.py')
ui=importlib.util.module_from_spec(spec);spec.loader.exec_module(ui)
req={'purpose':'Example request','source_hint':'Example','required_fields':['Id']}
c={'object_key':'a','object':{'database_name':'DEMO_Example','schema_name':'dbo','object_name':'Output'},'total':1,'matched':1,'score':90,'field_map':[],'confidence_label':'test'}
if not core.list_reviews():
 core.save_review(req,c,[],'PIC','legacy note',['DEMO_Example'],1)
 ticks=iter([10.0,22.5]);r=AnalysisTimer(req,['DEMO_Example'],1,clock=lambda:next(ticks)).finish()
 core.save_review(req,dict(c,analysis_runtime=r),[],'PIC','timed note',['DEMO_Example'],1)
ui.page_history()
'''
    h = AppTest.from_string('ROOT_PATH='+repr(str(ROOT))+'\n'+history_code,default_timeout=20).run()
    assert not h.exception,[e.value for e in h.exception]
    values = h.dataframe[0].value['Analyze time (s)']
    assert values.isna().sum() == 1 and 12.5 in values.values
    for option in list(h.selectbox[0].options):
        # Dropdown displays stable IDs and keeps the correct timing with the record.
        index = h.selectbox[0].options.index(option)
        h.selectbox[0].select_index(index).run();assert not h.exception
    print('PASS UI: every Analyze gets a unique run, first support is timed, cache is reused,')
    print('         no-candidate/failure states and mixed legacy/timed Mapping History work.')


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--ui',action='store_true');args=parser.parse_args()
    with TemporaryDirectory() as directory:
        temp=Path(directory)
        with patch.dict(os.environ, {'OJT2_APP_DATA_DIR':str(temp/'appdata')}):
            persistence(temp, measured())
            if args.ui:ui_tests()
