from dataclasses import dataclass
from datetime import datetime, timedelta
from django.utils import timezone

GRACE_MINUTES = 15
NO_SHOW_MINUTES = 120
EARLY_WINDOW_MINUTES = 60


def aware_combine(d, t):
    return timezone.make_aware(datetime.combine(d, t))


def shift_datetimes(shift):
    start = aware_combine(shift.date, shift.start_time)
    end = aware_combine(shift.date, shift.end_time)
    if end <= start:
        return start, None
    return start, end


def session_belongs_to_shift_date(session, shift_date):
    if not session.clock_in_time:
        return False
    return timezone.localtime(session.clock_in_time).date() == shift_date


def session_overlaps_shift(session, shift_start, shift_end, now=None):
    if not session.clock_in_time or not shift_end:
        return False
    if timezone.localtime(session.clock_in_time).date() != shift_start.date():
        return False
    out = session.clock_out_time or now or timezone.now()
    return session.clock_in_time <= shift_end and out >= shift_start


def classify_shift(shift, sessions, now=None):
    now = now or timezone.now()
    start, end = shift_datetimes(shift)
    if end is None:
        return {"status": "UNSUPPORTED_OVERNIGHT", "covered": False, "matched_in": None, "minutes_late": None}
    day_sessions = [s for s in sessions if session_belongs_to_shift_date(s, shift.date)]
    window_start = start - timedelta(minutes=EARLY_WINDOW_MINUTES)
    window_end = start + timedelta(minutes=NO_SHOW_MINUTES)
    matched = next((s.clock_in_time for s in day_sessions if s.clock_in_time and window_start <= s.clock_in_time <= window_end), None)
    covered = any(session_overlaps_shift(s, start, end, now) for s in day_sessions)
    if not covered:
        return {"status": "NO_SHOW", "covered": False, "matched_in": matched, "minutes_late": None}
    if matched is None:
        return {"status": "COVERED", "covered": True, "matched_in": None, "minutes_late": None}
    minutes = max(0, int((matched - start).total_seconds() // 60))
    return {"status": "ON_TIME" if minutes <= GRACE_MINUTES else "LATE", "covered": True, "matched_in": matched, "minutes_late": minutes}
