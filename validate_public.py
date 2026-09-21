"""Independent, fail-closed version-1 public artifact boundary (stdlib only).

Keep this runner-side module out of the Pages artifact. No private exporter
imports: changes to the producer must be reviewed against this contract.
"""
from datetime import date, datetime
import json
import math
import re

NOTES = frozenset({
    'Records are incomplete; zero-record days do not mean no feeding.',
    'Sessions group starts within 60 minutes of the first start; explicit sessions remain intact.',
    'Durations sum nursing time, not elapsed session spans; unknown and active durations are not estimated.',
    'Daily totals include known durations only; means exclude sessions with any unknown duration.',
    'Daily minutes are rounded to 5 minutes and start-to-start intervals to 0.5 hours; counts are exact.',
    'Daily counts and durations are assigned to the session start date in Europe/Zurich.',
    'Only the five most recent sessions include detail; retrospective side order is unknown.',
})
ERROR = 'Invalid public export'


def require(condition):
    if not condition:
        raise ValueError(ERROR)


def fields(value, names):
    require(type(value) is dict and set(value) == set(names.split()))


def array(value):
    require(type(value) is list)


def number(value, step=None):
    if value is None:
        return
    require(type(value) in (int, float))
    require(math.isfinite(value) and value >= 0)
    if step is not None:
        require(value % step == 0)


def count(value):
    require(type(value) is int and value >= 0)


def instant(value):
    require(type(value) is str and re.fullmatch(
        r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})', value))
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        require(parsed.utcoffset() is not None)
        return parsed
    except (ValueError, OverflowError):
        raise ValueError(ERROR) from None


def day(value):
    require(type(value) is str and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value))
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(ERROR) from None


def _validate(payload):
    fields(payload, 'version checkedAt dataAsOf timezone recent days coverage' + (' analysis' if payload.get('version') == 2 else ''))
    require(type(payload['version']) is int and payload['version'] in (1, 2))
    if payload['version'] == 2:
        from zoneinfo import ZoneInfo
        from datetime import timedelta
        a = payload['analysis']
        fields(a, 'windowStart windowEnd gaps sideDays')
        end = instant(payload['checkedAt']).astimezone(ZoneInfo('Europe/Zurich')).date()
        require(day(a['windowEnd']) == end and day(a['windowStart']) == end-timedelta(days=13))
        array(a['gaps']); array(a['sideDays'])
        starts = []
        for gap in a['gaps']:
            fields(gap, 'startedAt gapMinutes status')
            start = instant(gap['startedAt'])
            require(day(a['windowStart']) <= start.astimezone(ZoneInfo('Europe/Zurich')).date() <= end)
            starts.append(start)
            require(gap['status'] in ('known','unknown','overlap'))
            number(gap['gapMinutes'])
            require((gap['gapMinutes'] is None) == (gap['status'] == 'unknown'))
            if gap['status'] == 'overlap': require(gap['gapMinutes'] == 0)
        require(starts == sorted(set(starts)))
        side_dates = []
        for row in a['sideDays']:
            fields(row, 'date leftMinutes rightMinutes complete')
            side_dates.append(day(row['date']))
            for key in ('leftMinutes','rightMinutes'):
                number(row[key]); require(row[key] is not None)
            require(type(row['complete']) is bool)
        require(side_dates == sorted(set(side_dates)))
        require([r['date'] for r in a['sideDays']] == [r['date'] for r in payload['days'] if r['sessions']])
    require(payload['timezone'] == 'Europe/Zurich')
    instant(payload['checkedAt'])
    array(payload['recent'])
    require(len(payload['recent']) <= 5)
    approved = set()
    starts = []
    for recent in payload['recent']:
        fields(recent, 'startedAt endedAt leftMinutes rightMinutes knownMinutes order segments grouped uncertain')
        start = instant(recent['startedAt'])
        starts.append(start)
        approved.add(start)
        end = None if recent['endedAt'] is None else instant(recent['endedAt'])
        if end is not None:
            require(end >= start)
            approved.add(end)
        for key in ('leftMinutes', 'rightMinutes', 'knownMinutes'):
            number(recent[key])
        for key in ('grouped', 'uncertain'):
            require(type(recent[key]) is bool)
        array(recent['segments'])
        segment_starts = []
        for segment in recent['segments']:
            fields(segment, 'side at minutes')
            require(type(segment['side']) is str and segment['side'] in ('left', 'right'))
            at = instant(segment['at'])
            require(at >= start and (end is None or at <= end))
            approved.add(at)
            segment_starts.append(at)
            number(segment['minutes'])
        require(segment_starts == sorted(segment_starts))
        if recent['order'] is not None:
            array(recent['order'])
            require(all(type(side) is str and side in ('left', 'right') for side in recent['order']))
            require(recent['order'] == [part['side'] for part in recent['segments']])
    require(starts == sorted(starts, reverse=True) and len(set(starts)) == len(starts))
    if payload['dataAsOf'] is None:
        require(not approved)
    else:
        require(instant(payload['dataAsOf']) in approved)
    array(payload['days'])
    dates = []
    total_sessions = 0
    for entry in payload['days']:
        fields(entry, 'date sessions knownDurationSessions totalMinutes meanMinutes meanIntervalHours')
        dates.append(day(entry['date']))
        count(entry['sessions'])
        count(entry['knownDurationSessions'])
        require(entry['knownDurationSessions'] <= entry['sessions'])
        total_sessions += entry['sessions']
        number(entry['totalMinutes'], 5)
        number(entry['meanMinutes'], 5)
        number(entry['meanIntervalHours'], 0.5)
        require((entry['meanMinutes'] is None) == (entry['knownDurationSessions'] == 0))
        if entry['sessions'] == 0:
            require(all(entry[key] is None for key in ('totalMinutes', 'meanMinutes', 'meanIntervalHours')))
    require(all((b-a).days == 1 for a, b in zip(dates, dates[1:])))
    require(len(payload['recent']) == min(5, total_sessions))
    coverage = payload['coverage']
    fields(coverage, 'start end notes')
    require(coverage['start'] == (dates[0].isoformat() if dates else None))
    require(coverage['end'] == (dates[-1].isoformat() if dates else None))
    array(coverage['notes'])
    require(all(type(note) is str and note in NOTES for note in coverage['notes']))
    require(len(coverage['notes']) == len(set(coverage['notes'])))


def validate_public(payload):
    """Return the validated object; reject with a payload-free ValueError."""
    try:
        _validate(payload)
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        raise ValueError(ERROR) from None
    return payload


def loads_public(raw):
    """Reject duplicate JSON keys too, before their values can be discarded."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result)
            result[key] = value
        return result
    try:
        require(len(raw) <= 1024 * 1024)
        payload = json.loads(raw, object_pairs_hook=unique)
        return validate_public(payload)
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
        raise ValueError(ERROR) from None
