from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from urllib import request as urlrequest, parse as urlparse
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
        has_prior_session = any(s.clock_in_time and s.clock_in_time < window_start for s in sessions)
        if now >= checkin_deadline or (has_prior_session and timezone.localtime(now).date() >= shift.date):
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


def approved_leave_employee_ids(target_date):
    from .models import LeaveRequest
    return set(LeaveRequest.objects.filter(status="APPROVED", date_from__lte=target_date, date_to__gte=target_date).values_list("employee_id", flat=True))


def resolve_fixed_schedule(division, target_date):
    from .models import ScheduleException, FixedScheduleRule
    exc = ScheduleException.objects.filter(division=division, date=target_date).first()
    if exc and not exc.is_workday:
        return None, None
    rule = FixedScheduleRule.objects.filter(division=division, weekday=target_date.weekday()).first()
    if exc and exc.is_workday and exc.start_time and exc.end_time:
        return {"start_time": exc.start_time, "end_time": exc.end_time}, rule
    if not rule or not rule.is_workday:
        return None, None
    return rule, rule


def generate_fixed_shifts(from_date=None, days=45, division_id=None, confirm=False, stdout=None):
    from .models import Division, EmployeeProfile, ShiftAssignment
    from django.db import transaction
    from django.utils import timezone
    from datetime import timedelta
    today = timezone.localdate()
    from_date = from_date or today
    qs = Division.objects.filter(is_active=True, schedule_mode="FIXED")
    if division_id:
        qs = qs.filter(id=division_id)
    counts = {"created": 0, "updated": 0, "skipped": 0, "unchanged": 0}
    for div in qs:
        employees = [p.employee for p in EmployeeProfile.objects.filter(division=div, is_rostered=True, employee__is_active=True).select_related("employee")]
        for offset in range(days):
            d = from_date + timedelta(days=offset)
            resolved, rule = resolve_fixed_schedule(div, d)
            if not resolved:
                counts["skipped"] += len(employees); continue
            start_time = resolved["start_time"] if isinstance(resolved, dict) else resolved.start_time
            end_time = resolved["end_time"] if isinstance(resolved, dict) else resolved.end_time
            for emp in employees:
                if ShiftAssignment.objects.filter(employee=emp, date=d, source="MANUAL").exists():
                    counts["skipped"] += 1; continue
                fixed = ShiftAssignment.objects.filter(employee=emp, date=d, source="FIXED").first()
                if fixed:
                    if fixed.start_time == start_time and fixed.end_time == end_time and fixed.division_id == div.id:
                        counts["unchanged"] += 1; continue
                    if d < today:
                        counts["skipped"] += 1; continue
                    counts["updated"] += 1
                    if confirm:
                        fixed.division = div; fixed.start_time = start_time; fixed.end_time = end_time; fixed.status = "APPROVED"; fixed.fixed_schedule_rule = rule; fixed.save(update_fields=["division","start_time","end_time","status","fixed_schedule_rule","updated_at"])
                    continue
                counts["created"] += 1
                if confirm:
                    with transaction.atomic():
                        if not ShiftAssignment.objects.filter(employee=emp, date=d, source="MANUAL").exists():
                            ShiftAssignment.objects.create(employee=emp, division=div, date=d, start_time=start_time, end_time=end_time, status="APPROVED", source="FIXED", fixed_schedule_rule=rule)
    return counts


def telegram_config():
    return {
        "enabled": attendance_setting("TELEGRAM_ALERTS_ENABLED", False),
        "token": attendance_setting("TELEGRAM_BOT_TOKEN", ""),
        "chat_ids": [c.strip() for c in attendance_setting("TELEGRAM_CHAT_IDS", "").split(",") if c.strip()],
        "timeout": attendance_setting("ATTENDANCE_ALERT_HTTP_TIMEOUT_SECONDS", 10),
    }


def sanitize_error(text):
    import re
    return re.sub(r"bot[0-9]+:[A-Za-z0-9_-]+", "bot<redacted>", str(text))[:500]


def send_telegram_message(text):
    cfg = telegram_config()
    if not cfg["enabled"] or not cfg["token"] or not cfg["chat_ids"]:
        return False, "Telegram disabled or incomplete"
    errors=[]
    for chat in cfg["chat_ids"]:
        try:
            data = urlparse.urlencode({"chat_id": chat, "text": text[:3500]}).encode()
            req = urlrequest.Request(f"https://api.telegram.org/bot{cfg['token']}/sendMessage", data=data, method="POST")
            with urlrequest.urlopen(req, timeout=cfg["timeout"]) as resp:
                if getattr(resp, "status", 200) >= 400:
                    errors.append(str(resp.status))
        except Exception as exc: errors.append(str(exc))
    return (not errors), sanitize_error("; ".join(errors))


def alert_candidates(target_date=None, event_type=None, division_id=None):
    from .models import LeaveRequest, AttendanceCorrectionRequest, AttendanceEvent, PinAttempt, ShiftAssignment
    from django.utils import timezone
    from datetime import datetime, timedelta
    target_date = target_date or timezone.localdate()
    start = timezone.make_aware(datetime.combine(target_date, datetime.min.time())); end = start + timedelta(days=1)
    candidates=[]
    def add(t,key,msg,emp=None,div=None):
        if event_type and t != event_type: return
        if division_id and (not div or div.id != int(division_id)): return
        candidates.append({"event_type":t,"dedupe_key":key,"message":msg,"employee":emp,"division":div,"target_date":target_date})
    for lr in LeaveRequest.objects.filter(status="SUBMITTED", created_at__date__gte=target_date-timedelta(days=attendance_setting("ATTENDANCE_ALERT_REQUEST_LOOKBACK_DAYS",7))).select_related("employee","employee__profile__division"):
        add("NEW_LEAVE_REQUEST", f"leave:{lr.id}", f"New leave request: {lr.employee.name} {lr.date_from} to {lr.date_to}", lr.employee, getattr(lr.employee.profile,'division',None) if hasattr(lr.employee,'profile') else None)
    for cr in AttendanceCorrectionRequest.objects.filter(status="SUBMITTED", created_at__date__gte=target_date-timedelta(days=attendance_setting("ATTENDANCE_ALERT_REQUEST_LOOKBACK_DAYS",7))).select_related("employee","employee__profile__division"):
        add("NEW_CORRECTION_REQUEST", f"correction:{cr.id}", f"New correction request: {cr.employee.name} {cr.request_type}", cr.employee, getattr(cr.employee.profile,'division',None) if hasattr(cr.employee,'profile') else None)
    leaves = approved_leave_employee_ids(target_date)
    shifts=ShiftAssignment.objects.filter(date=target_date,status="APPROVED",employee__is_active=True).select_related("employee","division")
    if division_id: shifts=shifts.filter(division_id=division_id)
    from .models import AttendanceSession
    sessions=list(AttendanceSession.objects.filter(clock_in_time__lt=end+timedelta(days=1), clock_in_time__gte=start-timedelta(days=1)))
    for sh in shifts:
        if sh.employee_id in leaves: continue
        res=classify_shift(sh,[s for s in sessions if s.employee_id==sh.employee_id], timezone.now())
        if res['status']=="NO_SHOW": add("NO_SHOW", f"noshow:{sh.employee_id}:{sh.id}:{target_date}", f"No-show: {sh.employee.name} on {target_date}", sh.employee, sh.division)
        if res.get('missing_clockout'): add("MISSING_CLOCKOUT", f"missing_clockout:{res['session'].id}:{sh.id}:{target_date}", f"Missing clock-out: {sh.employee.name} on {target_date}", sh.employee, sh.division)
    for ev in AttendanceEvent.objects.filter(created_at__gte=start,created_at__lt=end,is_proxy=True).select_related("subject_employee","subject_employee__profile__division"):
        div=getattr(getattr(ev.subject_employee,'profile',None),'division',None); add("PROXY_ATTENDANCE", f"proxy:{ev.id}", f"Proxy attendance recorded for {ev.subject_employee.name}", ev.subject_employee, div)
    for pa in PinAttempt.objects.filter(locked_until__isnull=False, locked_until__gte=start).select_related("employee","employee__profile__division"):
        div=getattr(getattr(pa.employee,'profile',None),'division',None); add("PIN_LOCKOUT", f"pin_lockout:{pa.employee_id}:{pa.purpose}:{pa.locked_until.isoformat()}", f"PIN lockout: {pa.employee.name} ({pa.purpose})", pa.employee, div)
    summary_time=str(attendance_setting("ATTENDANCE_ALERT_DAILY_SUMMARY_TIME","18:00"))
    if timezone.localtime().strftime("%H:%M") >= summary_time:
        add("DAILY_SUMMARY", f"daily_summary:{target_date}", f"Daily summary {target_date}: expected {shifts.count()}, pending leave {LeaveRequest.objects.filter(status='SUBMITTED').count()}, pending corrections {AttendanceCorrectionRequest.objects.filter(status='SUBMITTED').count()}")
    return candidates


def process_alerts(send=False, event_type=None, division_id=None, target_date=None, retry_failed=False, max_retries=3):
    from .models import NotificationDelivery
    out=[]
    for c in alert_candidates(target_date, event_type, division_id):
        rec, _ = NotificationDelivery.objects.get_or_create(dedupe_key=c['dedupe_key'], defaults={k:c[k] for k in ['event_type','employee','division','target_date']})
        if rec.status == 'SENT': continue
        if rec.status == 'FAILED' and (not retry_failed or rec.attempts >= max_retries): continue
        if not send: out.append((rec, c['message'], 'DRY_RUN')); continue
        ok, err = send_telegram_message(c['message'])
        rec.attempts += 1; rec.last_attempt_at = timezone.now()
        if ok: rec.status='SENT'; rec.sent_at=timezone.now(); rec.last_error=''
        else: rec.status='FAILED'; rec.last_error=err
        rec.save(update_fields=['attempts','last_attempt_at','status','sent_at','last_error'])
        out.append((rec,c['message'],rec.status))
    return out
