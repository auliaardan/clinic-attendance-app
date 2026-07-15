from datetime import timedelta, datetime, date
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.files.base import ContentFile
from django.db import IntegrityError, models, transaction
from django.http import JsonResponse, Http404, FileResponse, HttpResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_http_methods

from .models import Division, DivisionRosterEditor
from .models import (
    Employee, AttendanceSession, AttendanceEvent,
    ShiftAssignment, LeaveRequest
)
from .models import (
    EmployeeProfile, ShiftTemplate
)
from .qr import make_qr_token, window_meta, token_expires_in
from .services import classify_shift, shift_datetimes, aware_combine as dt_combine, grace_minutes, no_show_minutes, early_window_minutes, missing_clockout_tolerance_minutes, long_open_session_hours
from .models import PinAttempt


def recompress_image(uploaded_file, *, max_side=1024, quality=75) -> ContentFile:
    """
    Convert uploaded image to JPEG, auto-rotate by EXIF, and resize so longest edge <= max_side.
    Returns a Django ContentFile ready to assign to ImageField.
    """
    try:
        img = Image.open(uploaded_file)
        img.verify()
        uploaded_file.seek(0)
        img = Image.open(uploaded_file)
        img = ImageOps.exif_transpose(img)
    except (UnidentifiedImageError, OSError, ValueError):
        raise ValueError("Invalid photo upload")  # fix iPhone/Android rotation

    # Convert to RGB for JPEG (handles PNG with alpha, etc.)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    elif img.mode == "L":
        img = img.convert("RGB")

    # Resize (preserve aspect ratio)
    w, h = img.size
    longest = max(w, h)
    if longest > max_side:
        scale = max_side / float(longest)
        new_size = (int(w * scale), int(h * scale))
        img = img.resize(new_size, Image.LANCZOS)

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    buf.seek(0)

    return ContentFile(buf.read())


def get_client_ip(request):
    return request.META.get("REMOTE_ADDR")


def home(request):
    employees = Employee.objects.filter(is_active=True).order_by("name")
    return render(request, "attendance/home.html", {"employees": employees})


def qr_display(request):
    return render(request, "attendance/display.html")


@require_http_methods(["GET"])
def api_qr(request):
    token = make_qr_token(window_seconds=60)
    meta = window_meta(window_seconds=60)
    return JsonResponse({"token": token, **meta})


@require_GET
def api_employee_status(request):
    employee_id = request.GET.get("employee_id", "")
    try:
        emp = Employee.objects.get(id=employee_id, is_active=True)
    except Employee.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Invalid employee"}, status=404)

    open_session = (
        AttendanceSession.objects
        .filter(employee=emp, is_open=True)
        .order_by("-id")
        .first()
    )

    # For clarity:
    # - if open_session exists => currently "IN" (working) => next_action should be "OUT"
    # - else => currently "OUT" (not checked-in) => next_action should be "IN"
    if open_session and open_session.clock_in_time and not open_session.clock_out_time:
        return JsonResponse({
            "ok": True,
            "employee_id": emp.id,
            "employee_name": emp.name,
            "current_state": "IN",
            "next_action": "OUT",
            "since": timezone.localtime(open_session.clock_in_time).isoformat(),
        })

    # no open session
    last_session = (
        AttendanceSession.objects
        .filter(employee=emp)
        .exclude(clock_in_time__isnull=True)
        .order_by("-id")
        .first()
    )

    return JsonResponse({
        "ok": True,
        "employee_id": emp.id,
        "employee_name": emp.name,
        "current_state": "OUT",
        "next_action": "IN",
        "since": timezone.localtime(last_session.clock_out_time).isoformat()
        if last_session and last_session.clock_out_time else None,
    })


@require_GET
def api_qr_check(request):
    token = request.GET.get("token", "")
    expires_in = token_expires_in(token, window_seconds=60, max_age_seconds=70)
    return JsonResponse({
        "valid": expires_in > 0,
        "expires_in": expires_in,
        **window_meta(window_seconds=60),
    })



PIN_THRESHOLD = 5
PIN_WINDOW = timedelta(minutes=15)
PIN_LOCKOUT = timedelta(minutes=15)

def pin_locked(employee, ip, purpose, now=None):
    now = now or timezone.now()
    rec = PinAttempt.objects.filter(employee=employee, client_ip=ip, purpose=purpose).first()
    return bool(rec and rec.locked_until and rec.locked_until > now)

def record_pin_success(employee, ip, purpose):
    PinAttempt.objects.filter(employee=employee, client_ip=ip, purpose=purpose).delete()

def record_pin_failure(employee, ip, purpose):
    now = timezone.now()
    rec, _ = PinAttempt.objects.get_or_create(employee=employee, client_ip=ip, purpose=purpose, defaults={"first_failed_at": now, "last_failed_at": now})
    if now - rec.first_failed_at > PIN_WINDOW:
        rec.failures = 0
        rec.first_failed_at = now
    rec.failures += 1
    rec.last_failed_at = now
    if rec.failures >= PIN_THRESHOLD:
        rec.locked_until = now + PIN_LOCKOUT
    rec.save()

def verify_pin_or_response(employee, raw_pin, ip, purpose):
    if pin_locked(employee, ip, purpose):
        return False, JsonResponse({"ok": False, "error": "Too many attempts. Try again later."}, status=429)
    if not employee.check_pin(raw_pin):
        record_pin_failure(employee, ip, purpose)
        return False, JsonResponse({"ok": False, "error": "Wrong PIN"}, status=403)
    record_pin_success(employee, ip, purpose)
    return True, None

@csrf_exempt
@require_http_methods(["POST"])
def api_clock(request):
    action = request.POST.get("action", "").upper()
    qr_token = request.POST.get("qr_token", "")
    subject_id = request.POST.get("subject_employee_id", "")
    subject_pin = request.POST.get("subject_pin", "")
    is_proxy = request.POST.get("is_proxy", "0") == "1"

    witness_id = request.POST.get("witness_employee_id", "")
    witness_pin = request.POST.get("witness_pin", "")

    if action not in ("IN", "OUT"):
        return JsonResponse({"ok": False, "error": "Invalid action"}, status=400)

    if token_expires_in(qr_token, window_seconds=60, max_age_seconds=70) <= 0:
        return JsonResponse({"ok": False, "error": "QR expired/invalid"}, status=403)

    photo = request.FILES.get("photo")
    if not photo:
        return JsonResponse({"ok": False, "error": "Photo is required"}, status=400)

    # Optional hard cap (good UX)
    MAX_UPLOAD = 10 * 1024 * 1024
    if getattr(photo, "size", 0) > MAX_UPLOAD:
        return JsonResponse({"ok": False, "error": "Photo too large (max 10MB)"}, status=413)

    try:
        subject = Employee.objects.get(id=subject_id, is_active=True)
    except Employee.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Invalid employee"}, status=404)

    ip = get_client_ip(request) or "0.0.0.0"
    ok, response = verify_pin_or_response(subject, subject_pin, ip, "SUBJECT")
    if not ok:
        return response

    witness = None
    if is_proxy:
        if not witness_id or not witness_pin:
            return JsonResponse({"ok": False, "error": "Witness required for proxy"}, status=400)
        try:
            witness = Employee.objects.get(id=witness_id, is_active=True)
        except Employee.DoesNotExist:
            return JsonResponse({"ok": False, "error": "Invalid witness"}, status=404)
        ok, response = verify_pin_or_response(witness, witness_pin, ip, "WITNESS")
        if not ok:
            return response

        if witness.id == subject.id:
            return JsonResponse({"ok": False, "error": "Witness cannot be the same person"}, status=400)

    # Now do the CPU work (recompress)
    try:
        compressed = recompress_image(photo, max_side=1024, quality=75)
    except ValueError:
        return JsonResponse({"ok": False, "error": "Invalid photo upload"}, status=400)
    filename = f"{subject.id}_{timezone.now().strftime('%Y%m%d_%H%M%S')}_{action}.jpg"
    photo_file = ContentFile(compressed.read(), name=filename)

    now = timezone.now()
    with transaction.atomic():
        subject = Employee.objects.select_for_update().get(id=subject.id)
        open_session = (AttendanceSession.objects.select_for_update()
                        .filter(employee=subject, is_open=True).order_by("-id").first())

        if action == "IN":
            if open_session and open_session.clock_in_time and not open_session.clock_out_time:
                return JsonResponse({"ok": False, "error": "Already clocked in"}, status=409)
            try:
                session = AttendanceSession.objects.create(employee=subject, clock_in_time=now, is_open=True)
            except IntegrityError:
                return JsonResponse({"ok": False, "error": "Already clocked in"}, status=409)
            AttendanceEvent.objects.create(
                event_type="IN", session=session, subject_employee=subject, witness_employee=witness,
                photo=photo_file, client_ip=get_client_ip(request),
                user_agent=request.META.get("HTTP_USER_AGENT", ""), is_proxy=is_proxy,
                note="PROXY" if is_proxy else "")
            return JsonResponse({"ok": True, "message": "Clock-in recorded", "time": now.isoformat()})

        if not open_session or not open_session.clock_in_time or open_session.clock_out_time:
            return JsonResponse({"ok": False, "error": "No open session to clock out"}, status=409)
        open_session.clock_out_time = now
        open_session.is_open = False
        open_session.save(update_fields=["clock_out_time", "is_open"])
        AttendanceEvent.objects.create(
            event_type="OUT", session=open_session, subject_employee=subject, witness_employee=witness,
            photo=photo_file, client_ip=get_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", ""), is_proxy=is_proxy,
            note="PROXY" if is_proxy else "")
        return JsonResponse({"ok": True, "message": "Clock-out recorded", "time": now.isoformat()})


def is_manager(user):
    return user.is_authenticated and user.is_staff  # simple & best practice


@login_required
@user_passes_test(is_manager)
def manager_dashboard(request):
    selected_date = _selected_date(request)
    division_id = request.GET.get("division") or ""
    context = _manager_context(selected_date, division_id)
    return render(request, "attendance/manager_dashboard.html", context)


def _selected_date(request):
    raw = request.GET.get("date")
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    return timezone.localdate()


def _manager_context(selected_date, division_id=""):
    start = timezone.make_aware(datetime.combine(selected_date, datetime.min.time()))
    end = start + timedelta(days=1)
    divisions = Division.objects.filter(is_active=True).order_by("name")
    division_filter = int(division_id) if str(division_id).isdigit() else None
    shifts_today = list(ShiftAssignment.objects.filter(date=selected_date, status="APPROVED").select_related("employee", "division"))
    if division_filter:
        shifts_today = [s for s in shifts_today if s.division_id == division_filter]
    approved_leave_ids = set(LeaveRequest.objects.filter(status="APPROVED", date_from__lte=selected_date, date_to__gte=selected_date).values_list("employee_id", flat=True))
    shifts_today = [s for s in shifts_today if s.employee_id not in approved_leave_ids]
    sessions = list(AttendanceSession.objects.filter(clock_in_time__lt=end + timedelta(days=1), clock_in_time__gte=start - timedelta(days=1)).select_related("employee"))
    open_sessions = list(AttendanceSession.objects.filter(is_open=True).select_related("employee", "employee__profile", "employee__profile__division").order_by("clock_in_time"))
    now = timezone.now()
    rows = []
    exceptions = []
    on_time = late = no_show = attended = missing_clockouts = 0
    proxy_event_ids = set(AttendanceEvent.objects.filter(created_at__gte=start, created_at__lt=end, is_proxy=True).values_list("session_id", flat=True))
    for sh in shifts_today:
        emp_sessions = [sess for sess in sessions + open_sessions if sess.employee_id == sh.employee_id]
        result = classify_shift(sh, emp_sessions, now)
        proxy = bool(result.get("session") and result["session"].id in proxy_event_ids)
        status = result["status"]
        if status in ("ON_TIME", "LATE"):
            attended += 1
            on_time += status == "ON_TIME"
            late += status == "LATE"
        elif status == "NO_SHOW":
            no_show += 1
        if result.get("missing_clockout"):
            missing_clockouts += 1
        row = {"employee": sh.employee, "division": sh.division, "shift": sh, "shift_start": shift_datetimes(sh)[0], "shift_end": shift_datetimes(sh)[1], "in_time": result.get("matched_in"), "out_time": result.get("qualifying_out"), "status": status, "minutes_late": result.get("minutes_late"), "missing_clockout": result.get("missing_clockout"), "proxy": proxy, "session": result.get("session")}
        rows.append(row)
        if status == "NO_SHOW":
            exceptions.append(_exception(sh.employee, sh.division, shift_datetimes(sh)[0], "No show", sh, "No qualifying attendance after the no-show threshold."))
        if status == "LATE":
            exceptions.append(_exception(sh.employee, sh.division, result.get("matched_in"), "Late arrival", sh, f"Arrived {result.get('minutes_late')} minutes after shift start."))
        if result.get("missing_clockout"):
            exceptions.append(_exception(sh.employee, sh.division, shift_datetimes(sh)[1], "Missing clock-out", sh, "Session is still open beyond shift end tolerance."))
        if proxy:
            exceptions.append(_exception(sh.employee, sh.division, result.get("matched_in"), "Proxy attendance", sh, "Attendance was recorded by a witness."))
    roster_emp_ids = {sh.employee_id for sh in shifts_today}
    today_events_qs = AttendanceEvent.objects.filter(created_at__gte=start, created_at__lt=end).select_related("subject_employee", "witness_employee", "session").order_by("-created_at")
    if division_filter:
        today_events_qs = today_events_qs.filter(subject_employee__profile__division_id=division_filter)
    for event in today_events_qs:
        div = getattr(getattr(event.subject_employee, "profile", None), "division", None)
        if event.is_proxy:
            exceptions.append(_exception(event.subject_employee, div, event.created_at, "Proxy attendance", None, "Attendance event was recorded by a proxy witness."))
        if event.subject_employee_id not in roster_emp_ids:
            exceptions.append(_exception(event.subject_employee, div, event.created_at, "Attendance without roster", None, "Attendance exists without an approved roster for this date."))
    locked_attempts = PinAttempt.objects.filter(locked_until__gt=now).select_related("employee", "employee__profile", "employee__profile__division")
    for pa in locked_attempts:
        div = getattr(getattr(pa.employee, "profile", None), "division", None)
        if not division_filter or (div and div.id == division_filter):
            exceptions.append(_exception(pa.employee, div, pa.locked_until, "PIN locked", None, f"{pa.purpose} PIN is locked after repeated failures."))
    long_threshold = timedelta(hours=long_open_session_hours())
    open_too_long = [s for s in open_sessions if s.clock_in_time and now - s.clock_in_time > long_threshold]
    for sess in open_too_long:
        if not any(r.get("session") and r["session"].id == sess.id for r in rows):
            div = getattr(getattr(sess.employee, "profile", None), "division", None)
            exceptions.append(_exception(sess.employee, div, sess.clock_in_time, "Long open session", None, "Open session exceeds the configured long-session threshold without a usable approved shift."))
    month_start = selected_date.replace(day=1)
    scheduled = len(shifts_today)
    return {"today": selected_date, "selected_date": selected_date, "selected_division": str(division_id), "divisions": divisions, "scheduled_shifts": scheduled, "attended_shifts": attended, "attendance_rate": round(attended / scheduled * 100, 1) if scheduled else 0, "on_time_shifts": on_time, "late_shifts": late, "no_show_shifts": no_show, "currently_open_sessions": len(open_sessions), "missing_clockouts": missing_clockouts, "locked_pin_attempts": locked_attempts.count(), "proxy_events_count": today_events_qs.filter(is_proxy=True).count(), "today_count": today_events_qs.count(), "punctual_rows": rows, "exceptions": exceptions, "open_sessions": open_sessions, "open_too_long": open_too_long, "today_events": today_events_qs[:200], "grace_minutes": grace_minutes(), "no_show_minutes": no_show_minutes(), "early_window_minutes": early_window_minutes(), "missing_clockout_tolerance_minutes": missing_clockout_tolerance_minutes(), "long_open_session_hours": long_open_session_hours(), "month_start": month_start, "monthly_scheduled": scheduled, "monthly_att_rate": round(attended / scheduled * 100, 1) if scheduled else 0, "monthly_ontime_rate": round(on_time / scheduled * 100, 1) if scheduled else 0, "monthly_late_rate": round(late / scheduled * 100, 1) if scheduled else 0, "top_late": [], "top_noshow": [], "week_start": selected_date - timedelta(days=selected_date.weekday()), "pending_rosters": []}


def _exception(employee, division, when, kind, shift, explanation):
    return {"employee": employee, "division": division, "when": when, "type": kind, "shift": shift, "explanation": explanation}


@login_required
@user_passes_test(is_manager)
def manager_attendance_csv(request):
    selected_date = _selected_date(request)
    division_id = request.GET.get("division") or ""
    context = _manager_context(selected_date, division_id)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="attendance-{selected_date}.csv"'
    import csv
    writer = csv.writer(response)
    writer.writerow(["Employee", "Division", "Shift date", "Shift start", "Shift end", "First qualifying clock-in", "Qualifying clock-out", "Calculated status", "Minutes late", "Missing clock-out", "Proxy", "Audit reference"])
    for r in context["punctual_rows"]:
        writer.writerow([r["employee"].name, r["division"].name if r["division"] else "", selected_date.isoformat(), r["shift_start"].isoformat(), r["shift_end"].isoformat(), r["in_time"].isoformat() if r["in_time"] else "", r["out_time"].isoformat() if r["out_time"] else "", r["status"], r["minutes_late"] if r["minutes_late"] is not None else "", "yes" if r["missing_clockout"] else "no", "yes" if r["proxy"] else "no", f"session:{r['session'].id}" if r["session"] else ""])
    return response


@login_required
@user_passes_test(is_manager)
def attendance_photo(request, event_id):
    event = get_object_or_404(AttendanceEvent, id=event_id)
    if not event.photo:
        raise Http404("Photo not found")
    try:
        return FileResponse(event.photo.open("rb"), content_type="image/jpeg")
    except (FileNotFoundError, ValueError, OSError):
        raise Http404("Photo not found")


def editable_divisions_for(user):
    if user.is_staff:
        return Division.objects.filter(is_active=True)
    return Division.objects.filter(
        id__in=DivisionRosterEditor.objects.filter(user=user).values("division_id")
    )


@login_required
@require_http_methods(["GET", "POST"])
def roster_week(request):
    # week_start as YYYY-MM-DD (Monday). default = current week Monday
    week_start_str = request.GET.get("week_start", "")
    today = timezone.localdate()

    if week_start_str:
        week_start = date.fromisoformat(week_start_str)
    else:
        week_start = today - timedelta(days=today.weekday())

    days = [week_start + timedelta(days=i) for i in range(7)]

    divisions_qs = editable_divisions_for(request.user)
    if not divisions_qs.exists():
        return render(request, "attendance/roster_week.html", {"error": "No division access."})

    division_id = request.GET.get("division")
    division = get_object_or_404(divisions_qs, id=division_id) if division_id else divisions_qs.order_by("name").first()

    # employees in this division
    employee_ids = EmployeeProfile.objects.filter(
        division=division,
        is_rostered=True,
        employee__is_active=True
    ).values_list("employee_id", flat=True)

    employees = list(
        Employee.objects.filter(id__in=employee_ids).order_by("name")
    )

    # shift templates available to this division
    templates = list(
        ShiftTemplate.objects.filter(division=division, is_active=True).order_by("start_time", "name")
    )

    # existing assignments in week
    existing = ShiftAssignment.objects.filter(
        division=division,
        date__in=days,
        employee__in=employees
    ).select_related("template", "employee").order_by("start_time")

    # Map: (emp_id, date) -> list[ShiftAssignment]
    existing_map = {}
    for s in existing:
        k = f"{s.employee_id}:{s.date.isoformat()}"
        existing_map.setdefault(k, []).append(s)

    # Status control:
    # - manager can directly "APPROVE" on save if you want; here we keep it SUBMITTED unless manager hits approve.
    if request.method == "POST":
        locked_exists = ShiftAssignment.objects.filter(division=division, date__in=days, status="APPROVED").exists()
        if locked_exists and not request.user.is_staff:
            return render(request, "attendance/roster_week.html", {"error": "This week contains approved assignments and is locked."}, status=403)
        # For each employee/day, we receive multi-select list: shifts_<empid>_<date> = [template_id, template_id...]
        # Replace unlocked assignments only.
        for emp in employees:
            for d in days:
                key = f"shifts_{emp.id}_{d.isoformat()}"
                selected_template_ids = request.POST.getlist(key)  # can be []

                # delete unlocked existing for that emp/day (within this division)
                ShiftAssignment.objects.filter(employee=emp, division=division, date=d).exclude(status="APPROVED").delete()

                for tid in selected_template_ids:
                    tmpl = next((t for t in templates if str(t.id) == str(tid)), None)
                    if not tmpl:
                        continue

                    ShiftAssignment.objects.create(
                        employee=emp,
                        division=division,
                        date=d,
                        template=tmpl,
                        start_time=tmpl.start_time,
                        end_time=tmpl.end_time,
                        status="SUBMITTED" if not request.user.is_staff else "APPROVED",
                        entered_by=request.user,
                        approved_by=request.user if request.user.is_staff else None,
                    )

        return redirect(f"{request.path}?division={division.id}&week_start={week_start.isoformat()}")

    # Build display helper: selected template IDs for each cell
    selected_ids = {}
    for emp in employees:
        for d in days:
            k = f"{emp.id}:{d.isoformat()}"
            selected_ids[k] = [a.template_id for a in existing_map.get(k, []) if a.template_id]

    is_locked = ShiftAssignment.objects.filter(
        division=division, date__in=days, status__in=["SUBMITTED", "APPROVED"]
    ).exists()

    has_unapproved = ShiftAssignment.objects.filter(
        division=division,
        date__in=days,
        status__in=["DRAFT", "SUBMITTED"],
    ).exists()

    context = {
        "division": division,
        "divisions": divisions_qs.order_by("name"),
        "templates": templates,
        "week_start": week_start,
        "days": days,
        "employees": employees,
        "existing_map": existing_map,
        "selected_ids": selected_ids,
        "is_manager": request.user.is_staff,
        "has_unapproved": has_unapproved,
        "is_locked": is_locked,
    }
    return render(request, "attendance/roster_week.html", context)


def session_overlaps_shift(sess, shift_start_dt, shift_end_dt, now):
    if not sess.clock_in_time:
        return False
    in_time = sess.clock_in_time
    out_time = sess.clock_out_time or now  # if open, treat as ongoing
    return (in_time <= shift_end_dt) and (out_time >= shift_start_dt)


@login_required
@user_passes_test(is_manager)
@require_http_methods(["POST"])
def approve_roster_week(request):
    division_id = request.POST.get("division")
    week_start = date.fromisoformat(request.POST.get("week_start"))
    days = [week_start + timedelta(days=i) for i in range(7)]

    ShiftAssignment.objects.filter(
        division_id=division_id,
        date__in=days,
        status__in=["DRAFT", "SUBMITTED"]
    ).update(status="APPROVED", approved_by=request.user)

    return redirect(f"/roster/?division={division_id}&week_start={week_start.isoformat()}")

from django.contrib import messages
from django.views.decorators.cache import never_cache
from .forms import EmployeeLoginForm, EmployeeLeaveRequestForm, AttendanceCorrectionRequestForm
from .models import AttendanceCorrectionRequest

EMP_SESSION_KEY = "employee_id"
EMP_AUTH_TS_KEY = "employee_authenticated_at"
EMP_PURPOSE = "EMPLOYEE_LOGIN"

def _employee_session_employee(request):
    emp_id = request.session.get(EMP_SESSION_KEY)
    ts = request.session.get(EMP_AUTH_TS_KEY)
    if not emp_id or not ts:
        return None
    try:
        auth_at = datetime.fromisoformat(ts)
        if timezone.is_naive(auth_at): auth_at = timezone.make_aware(auth_at)
    except (TypeError, ValueError):
        request.session.flush(); return None
    if timezone.now() - auth_at > timedelta(minutes=30):
        request.session.flush(); return None
    request.session[EMP_AUTH_TS_KEY] = timezone.now().isoformat()
    request.session.set_expiry(1800)
    try:
        return Employee.objects.select_related("profile", "profile__division").get(id=emp_id, is_active=True)
    except Employee.DoesNotExist:
        request.session.flush(); return None

def employee_required(view_func):
    def wrapper(request, *args, **kwargs):
        emp = _employee_session_employee(request)
        if not emp: return redirect("employee_login")
        request.employee = emp
        return view_func(request, *args, **kwargs)
    return never_cache(wrapper)

@never_cache
@require_http_methods(["GET", "POST"])
def employee_login(request):
    if request.method == "POST":
        form = EmployeeLoginForm(request.POST)
        if form.is_valid():
            emp = form.cleaned_data["employee"]; ip = get_client_ip(request) or "0.0.0.0"
            ok, _ = verify_pin_or_response(emp, form.cleaned_data["pin"], ip, EMP_PURPOSE)
            if ok:
                request.session.flush(); request.session.cycle_key()
                request.session[EMP_SESSION_KEY] = emp.id
                request.session[EMP_AUTH_TS_KEY] = timezone.now().isoformat()
                request.session.set_expiry(1800)
                return redirect("employee_dashboard")
            form.add_error(None, "Nama staff atau PIN tidak valid, atau akun terkunci sementara.")
    else:
        form = EmployeeLoginForm()
    return render(request, "attendance/employee_login.html", {"form": form})

@require_http_methods(["POST"])
def employee_logout(request):
    request.session.flush()
    return redirect("employee_login")

@employee_required
def employee_dashboard(request):
    emp=request.employee; today=timezone.localdate(); now=timezone.now()
    sessions=list(AttendanceSession.objects.filter(employee=emp, clock_in_time__gte=now-timedelta(days=30)).order_by("-clock_in_time"))
    shifts=list(ShiftAssignment.objects.filter(employee=emp, status="APPROVED", date__gte=today, date__lte=today+timedelta(days=14)).order_by("date","start_time"))
    today_shifts=[s for s in shifts if s.date==today]
    proxy_ids=set(AttendanceEvent.objects.filter(subject_employee=emp,is_proxy=True).values_list("session_id",flat=True))
    history=[]
    for s in sessions:
        dur = s.clock_out_time - s.clock_in_time if s.clock_in_time and s.clock_out_time else None
        history.append({"session":s,"duration":dur,"proxy":s.id in proxy_ids})
    open_session=AttendanceSession.objects.filter(employee=emp,is_open=True).first()
    return render(request,"attendance/employee_dashboard.html",{"employee":emp,"division":getattr(getattr(emp,"profile",None),"division",None),"state":"IN" if open_session else "OUT","today_shifts":today_shifts,"roster":shifts,"history":history,"leave_requests":LeaveRequest.objects.filter(employee=emp).order_by("-created_at")[:20],"correction_requests":AttendanceCorrectionRequest.objects.filter(employee=emp).order_by("-created_at")[:20]})

@employee_required
@require_http_methods(["GET","POST"])
def employee_leave_new(request):
    form=EmployeeLeaveRequestForm(request.POST or None, employee=request.employee)
    if request.method=="POST" and form.is_valid():
        form.save(); messages.success(request,"Pengajuan cuti terkirim."); return redirect("employee_dashboard")
    return render(request,"attendance/employee_form.html",{"form":form,"title":"Ajukan Cuti"})

@employee_required
@require_http_methods(["GET","POST"])
def employee_correction_new(request):
    form=AttendanceCorrectionRequestForm(request.POST or None, employee=request.employee)
    if request.method=="POST" and form.is_valid():
        form.save(); messages.success(request,"Pengajuan koreksi terkirim."); return redirect("employee_dashboard")
    return render(request,"attendance/employee_form.html",{"form":form,"title":"Ajukan Koreksi Absensi"})

@employee_required
@require_http_methods(["POST"])
def employee_correction_cancel(request, pk):
    corr=get_object_or_404(AttendanceCorrectionRequest, pk=pk, employee=request.employee, status="SUBMITTED")
    corr.status="CANCELLED"; corr.save(update_fields=["status"]); return redirect("employee_dashboard")

@login_required
@user_passes_test(is_manager)
def manager_requests(request):
    status=request.GET.get("status") or "SUBMITTED"; division=request.GET.get("division") or ""
    leaves=LeaveRequest.objects.filter(status=status).select_related("employee","employee__profile","employee__profile__division")
    corrections=AttendanceCorrectionRequest.objects.filter(status=status).select_related("employee","employee__profile","employee__profile__division","session")
    if division.isdigit():
        leaves=leaves.filter(employee__profile__division_id=division); corrections=corrections.filter(employee__profile__division_id=division)
    return render(request,"attendance/manager_requests.html",{"leaves":leaves,"corrections":corrections,"status":status,"divisions":Division.objects.filter(is_active=True)})

@login_required
@user_passes_test(is_manager)
@require_http_methods(["POST"])
def manager_leave_action(request, pk, action):
    obj=get_object_or_404(LeaveRequest, pk=pk, status="SUBMITTED")
    if action in ("approve","reject"):
        obj.status="APPROVED" if action=="approve" else "REJECTED"; obj.approved_by=request.user; obj.save(update_fields=["status","approved_by"])
    return redirect("manager_requests")

@login_required
@user_passes_test(is_manager)
@require_http_methods(["POST"])
def manager_correction_action(request, pk, action):
    obj=get_object_or_404(AttendanceCorrectionRequest, pk=pk, status="SUBMITTED")
    if action in ("approve","reject"):
        obj.status="APPROVED" if action=="approve" else "REJECTED"; obj.reviewed_by=request.user; obj.reviewed_at=timezone.now(); obj.manager_note=request.POST.get("manager_note","")[:1000]
        obj.save(update_fields=["status","reviewed_by","reviewed_at","manager_note"])
    return redirect("manager_requests")
