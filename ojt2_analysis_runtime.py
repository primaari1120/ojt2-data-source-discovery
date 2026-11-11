"""Measured Analyze runtime bound to the exact request, scope and catalog revision.

Pure helpers; no SQLite/network access. Duration uses perf_counter, not wall time.
Old records have no timing and remain unknown rather than being assigned zero.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from time import perf_counter
from uuid import UUID, uuid4


SCOPE = 'planner_discovery_initial_support'


def context_key(requirement: dict, source_scope: list[str], catalog_run_id) -> str:
    payload = {'requirement': requirement, 'databases': sorted(source_scope or []),
               'catalog_run_id': str(catalog_run_id)}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def _utc_stamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Runtime timestamps must be timezone-aware.')
    return value.astimezone(timezone.utc).isoformat(timespec='milliseconds')


class AnalysisTimer:
    def __init__(self, requirement, source_scope, catalog_run_id, *, trigger='analyze', clock=None, now=None):
        self._clock = clock or perf_counter
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._start = self._clock()
        self._started_at = _utc_stamp(self._now())
        self._key = context_key(requirement, source_scope, catalog_run_id)
        self._trigger = trigger
        self._id = str(uuid4())
        self._result = None

    def finish(self, status='completed') -> dict:
        if self._result is None:
            if status not in {'completed', 'no_candidates', 'failed'}:
                raise ValueError('Invalid Analyze status.')
            seconds = self._clock() - self._start
            if not math.isfinite(seconds) or seconds < 0:
                raise ValueError('Invalid monotonic duration.')
            self._result = {'schema_version': 1, 'run_id': self._id, 'status': status,
                            'started_at_utc': self._started_at, 'finished_at_utc': _utc_stamp(self._now()),
                            'duration_seconds': float(seconds), 'trigger': self._trigger,
                            'timing_scope': SCOPE, 'context_key': self._key}
        return dict(self._result)


def normalize_runtime(value) -> dict | None:
    if not isinstance(value, dict) or type(value.get('schema_version')) is not int or value['schema_version'] != 1 or value.get('timing_scope') != SCOPE:
        return None
    try:
        seconds = value['duration_seconds']
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0:
            return None
        if value['status'] not in {'completed', 'no_candidates', 'failed'}:
            return None
        run_id = str(UUID(value['run_id']))
        key = value['context_key']
        if not isinstance(key, str) or len(key) != 64 or any(c not in '0123456789abcdef' for c in key):
            return None
        started = _utc_stamp(datetime.fromisoformat(value['started_at_utc'].replace('Z', '+00:00')))
        finished = _utc_stamp(datetime.fromisoformat(value['finished_at_utc'].replace('Z', '+00:00')))
        trigger = value.get('trigger', 'analyze')
        if trigger not in {'analyze', 'alias_feedback', 'manual_correction', 'metadata_feedback'}:
            return None
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return None
    return {'schema_version': 1, 'run_id': run_id, 'status': value['status'],
            'started_at_utc': started, 'finished_at_utc': finished, 'duration_seconds': float(seconds),
            'trigger': trigger, 'timing_scope': SCOPE, 'context_key': key}


def runtime_for_context(value, requirement, source_scope, catalog_run_id) -> dict | None:
    runtime = normalize_runtime(value)
    if runtime is None:
        return None
    try:
        return runtime if runtime['context_key'] == context_key(requirement, source_scope, catalog_run_id) else None
    except (TypeError, ValueError):
        return None


def history_runtime(record) -> dict | None:
    try:
        summary = json.loads(record.get('score_json') or '{}')
        if not isinstance(summary, dict):
            return None
        return runtime_for_context(summary.get('analysis_runtime'),
            json.loads(record['requirement_json']), json.loads(record['source_scope']), record['catalog_run_id'])
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


def format_duration(runtime) -> str:
    runtime = normalize_runtime(runtime)
    return f"{runtime['duration_seconds']:.2f} s" if runtime else '—'
