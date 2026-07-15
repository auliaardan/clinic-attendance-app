from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone


def attendance_setting(name, default):
    return getattr(settings, name, default)


def grace_minutes(): return attendance_setting("ATTENDANCE_GRACE_PERIOD_MINUTES", 15)
def no_show_minutes(): return attendance_setting("ATTENDANCE_NO_SHOW_THRESHOLD_MINUTES", 120)
def early_window_minutes(): return attendance_setting("ATTENDANCE_EARLY_WINDOW_MINUTES", 60)
def missing_clockout_tolerance_minutes(): return attendance_setting("ATTENDANCE_MISSING_CLOCKOUT_TOLERANCE_MINUTES", 60)
def long_open_session_hours(): return attendance_setting("ATTENDANCE_LONG_OPEN_SESSION_THRESHOLD_HOURS", 10)

# Backward-compatible constants for older imports/tests.
GRACE_MINUTES = 15
NO_SHOW_MINUTES = 120
EARLY_WINDOW_MINUTES = 60


def aware_combine(d, t):
    return timezone.make_aware(datetime.combine(d, t))


def shift_datetimes(shift):
    start = aware_combine(shift.date, shift.start_time)
    end = aware_combine(shift.date, shift.end_time)
    if end <= start:
        end += timedelta(days=1)
    return start, end


def session_belongs_to_shift_date(session, shift_date):
    if not session.clock_in_time:
        return False
    return timezone.localtime(session.clock_in_time).date() == shift_date


def effective_session_end(session, now=None):
    if session.clock_out_time:
        return session.clock_out_time
    return now or timezone.now()


def session_overlaps_shift(session, shift_start, shift_end, now=None):
    if not session.clock_in_time or not shift_end:
        return False
    out = effective_session_end(session, now)
    return session.clock_in_time <= shift_end and out >= shift_start


def session_overlaps_window(session, window_start, window_end, now=None):
    if not session.clock_in_time:
        return False
    out = effective_session_end(session, now)
    return session.clock_in_time <= window_end and out >= window_start


def classify_shift(shift, sessions, now=None):
    now = now or timezone.now()
    start, end = shift_datetimes(shift)
    window_start = start - timedelta(minutes=early_window_minutes())
    window_end = end + timedelta(minutes=missing_clockout_tolerance_minutes())
    checkin_deadline = start + timedelta(minutes=no_show_minutes())
    relevant = [s for s in sessions if session_overlaps_window(s, window_start, window_end, now)]
    matched_session = next((s for s in relevant if s.clock_in_time and window_start <= s.clock_in_time <= checkin_deadline), None)
    matched_in = matched_session.clock_in_time if matched_session else None
    qualifying_out = None
    missing_clockout = False
    if matched_session:
        qualifying_out = matched_session.clock_out_time
        missing_clockout = bool(matched_session.is_open and not matched_session.clock_out_time and now > end + timedelta(minutes=missing_clockout_tolerance_minutes()))
    covered = bool(matched_session) and matched_session.clock_in_time <= end
    if not covered:
        if now >= checkin_deadline:
            return {"status": "NO_SHOW", "covered": False, "matched_in": matched_in, "qualifying_out": None, "minutes_late": None, "missing_clockout": False, "session": None}
        return {"status": "PENDING", "covered": False, "matched_in": matched_in, "qualifying_out": None, "minutes_late": None, "missing_clockout": False, "session": None}
    minutes = max(0, int((matched_in - start).total_seconds() // 60)) if matched_in else None
    status = "ON_TIME" if minutes is not None and minutes <= grace_minutes() else "LATE"
    return {"status": status, "covered": True, "matched_in": matched_in, "qualifying_out": qualifying_out, "minutes_late": minutes, "missing_clockout": missing_clockout, "session": matched_session}


def approved_shift_queryset_for_day(model, selected_date, division_id=None):
    qs = model.objects.filter(date=selected_date, status="APPROVED").select_related("employee", "division")
    if division_id:
        qs = qs.filter(division_id=division_id)
    return qs
