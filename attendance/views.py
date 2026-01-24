from datetime import timedelta, datetime, date
from io import BytesIO

from PIL import Image, ImageOps
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.files.base import ContentFile
from django.db import models
from django.http import JsonResponse
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


def recompress_image(uploaded_file, *, max_side=1024, quality=75) -> ContentFile:
    """
    Convert uploaded image to JPEG, auto-rotate by EXIF, and resize so longest edge <= max_side.
    Returns a Django ContentFile ready to assign to ImageField.
    """
    img = Image.open(uploaded_file)
    img = ImageOps.exif_transpose(img)  # fix iPhone/Android rotation

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

    if not subject.check_pin(subject_pin):
        return JsonResponse({"ok": False, "error": "Wrong PIN"}, status=403)

    witness = None
    if is_proxy:
        if not witness_id or not witness_pin:
            return JsonResponse({"ok": False, "error": "Witness required for proxy"}, status=400)
        try:
            witness = Employee.objects.get(id=witness_id, is_active=True)
        except Employee.DoesNotExist:
            return JsonResponse({"ok": False, "error": "Invalid witness"}, status=404)
        if not witness.check_pin(witness_pin):
            return JsonResponse({"ok": False, "error": "Wrong witness PIN"}, status=403)

        if witness.id == subject.id:
            return JsonResponse({"ok": False, "error": "Witness cannot be the same person"}, status=400)

    # Now do the CPU work (recompress)
    compressed = recompress_image(photo, max_side=1024, quality=75)
    filename = f"{subject.id}_{timezone.now().strftime('%Y%m%d_%H%M%S')}_{action}.jpg"
    photo_file = ContentFile(compressed.read(), name=filename)

    now = timezone.now()
    open_session = AttendanceSession.objects.filter(employee=subject, is_open=True).order_by("-id").first()

    if action == "IN":
        if open_session and open_session.clock_in_time and not open_session.clock_out_time:
            return JsonResponse({"ok": False, "error": "Already clocked in"}, status=409)

        session = AttendanceSession.objects.create(
            employee=subject,
            clock_in_time=now,
            is_open=True
        )

        AttendanceEvent.objects.create(
            event_type="IN",
            session=session,
            subject_employee=subject,
            witness_employee=witness,
            photo=photo_file,
            client_ip=get_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            is_proxy=is_proxy,
            note="PROXY" if is_proxy else ""
        )

        return JsonResponse({"ok": True, "message": "Clock-in recorded", "time": now.isoformat()})

    # OUT
    if not open_session or not open_session.clock_in_time or open_session.clock_out_time:
        return JsonResponse({"ok": False, "error": "No open session to clock out"}, status=409)

    open_session.clock_out_time = now
    open_session.is_open = False
    open_session.save(update_fields=["clock_out_time", "is_open"])

    AttendanceEvent.objects.create(
        event_type="OUT",
        session=open_session,
        subject_employee=subject,
        witness_employee=witness,
        photo=photo_file,  # ✅ compressed here too
        client_ip=get_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", ""),
        is_proxy=is_proxy,
        note="PROXY" if is_proxy else ""
    )

    return JsonResponse({"ok": True, "message": "Clock-out recorded", "time": now.isoformat()})


def is_manager(user):
    return user.is_authenticated and user.is_staff  # simple & best practice


GRACE_MINUTES = 15
NO_SHOW_MINUTES = 120
EARLY_WINDOW_MINUTES = 60


def dt_combine(d, t):
    return timezone.make_aware(datetime.combine(d, t))


@login_required
@user_passes_test(is_manager)
def manager_dashboard(request):
    today = timezone.localdate()

    # day bounds
    start = timezone.make_aware(datetime.combine(today, datetime.min.time()))
    end = start + timedelta(days=1)

    # month bounds (current month)
    month_start = today.replace(day=1)
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    month_end = next_month  # exclusive bound

    # week bounds (Monday-start)
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=7)

    pending_qs = (
        ShiftAssignment.objects.filter(
            date__gte=week_start,
            date__lt=week_end,
            status="SUBMITTED",
        )
        .select_related("division")
        .values("division_id", "division__name")
        .annotate(count=models.Count("id"))
        .order_by("division__name")
    )

    pending_rosters = []
    for row in pending_qs:
        pending_rosters.append({
            "division_id": row["division_id"],
            "division_name": row["division__name"],
            "count": row["count"],
            "week_start": week_start,
        })

    # --- LEAVE (approved) ---
    approved_leave_today_emp_ids = set(
        LeaveRequest.objects.filter(
            status="APPROVED",
            date_from__lte=today,
            date_to__gte=today,
        ).values_list("employee_id", flat=True)
    )

    # --- ROSTER: shifts today (approved only) ---
    shifts_today = list(
        ShiftAssignment.objects.filter(
            date=today,
            status="APPROVED",
        ).select_related("employee", "division")
    )

    # exclude staff on approved leave
    shifts_today = [s for s in shifts_today if s.employee_id not in approved_leave_today_emp_ids]

    # sessions today (for matching)
    sessions_today = list(
        AttendanceSession.objects.filter(
            clock_in_time__gte=start, clock_in_time__lt=end
        ).select_related("employee")
    )
    # plus open sessions from previous day (still open now) - for "missing OUT"
    open_sessions = AttendanceSession.objects.filter(is_open=True).select_related("employee").order_by("clock_in_time")

    # Build quick map: employee_id -> list of their sessions today sorted by clock_in_time
    sessions_by_emp = {}
    for s in sorted(sessions_today, key=lambda x: x.clock_in_time or start):
        sessions_by_emp.setdefault(s.employee_id, []).append(s)

    # ✅ include open sessions BEFORE shift calculations
    for s in open_sessions:
        sessions_by_emp.setdefault(s.employee_id, []).append(s)

    # ✅ sort each list
    for emp_id in sessions_by_emp:
        sessions_by_emp[emp_id] = sorted(sessions_by_emp[emp_id], key=lambda x: x.clock_in_time or start)

    # --- PUNCTUALITY classification per scheduled shift ---
    punctual_rows = []
    on_time = late = no_show = attended = covered_only = 0
    now = timezone.now()

    for sh in shifts_today:
        shift_start_dt = dt_combine(today, sh.start_time)
        shift_end_dt = dt_combine(today, sh.end_time)

        window_start = shift_start_dt - timedelta(minutes=EARLY_WINDOW_MINUTES)
        window_end = shift_start_dt + timedelta(minutes=NO_SHOW_MINUTES)

        emp_sessions = sessions_by_emp.get(sh.employee_id, [])

        # 1) punctuality (per-shift clock-in near shift start)
        matched_in = None
        for sess in emp_sessions:
            if sess.clock_in_time and window_start <= sess.clock_in_time <= window_end:
                matched_in = sess.clock_in_time
                break

        # 2) coverage (long shift policy): any session overlaps shift interval
        covered = any(session_overlaps_shift(sess, shift_start_dt, shift_end_dt, now) for sess in emp_sessions)

        if not covered:
            status = "NO_SHOW"
            minutes_late = None
            no_show += 1
        else:
            attended += 1

            if matched_in is None:
                # covered by a long session, but no clock-in near shift start
                status = "COVERED"
                minutes_late = None
                covered_only += 1

                # decide whether this counts as "on time" KPI:
                # I suggest YES because the person was present during the shift.
                on_time += 1
            else:
                diff_min = int((matched_in - shift_start_dt).total_seconds() // 60)
                minutes_late = max(0, diff_min)
                if minutes_late <= GRACE_MINUTES:
                    status = "ON_TIME"
                    on_time += 1
                else:
                    status = "LATE"
                    late += 1

        punctual_rows.append({
            "employee": sh.employee,
            "division": getattr(sh, "division", None),
            "shift_start": shift_start_dt,
            "shift_end": shift_end_dt,
            "in_time": matched_in,
            "status": status,
            "minutes_late": minutes_late,
        })

    scheduled = len(shifts_today)
    attendance_rate = round((attended / scheduled) * 100, 1) if scheduled else 0.0
    on_time_rate = round((on_time / scheduled) * 100, 1) if scheduled else 0.0
    late_rate = round((late / scheduled) * 100, 1) if scheduled else 0.0

    # --- EVENTS today (keep your existing table) ---
    today_events_qs = (AttendanceEvent.objects
                       .filter(created_at__gte=start, created_at__lt=end)
                       .select_related("subject_employee", "witness_employee", "session")
                       .order_by("-created_at")
                       )
    proxy_events_qs = today_events_qs.filter(is_proxy=True)

    # --- Missing OUT and too-long open sessions ---
    now = timezone.now()
    open_too_long = []
    for s in open_sessions:
        if s.clock_in_time and (now - s.clock_in_time) > timedelta(hours=10):
            open_too_long.append(s)
    # ✅ COPY-PASTE PATCH (monthly long-shift support)
    # Put this inside manager_dashboard(), replacing your existing "Monthly insights (per-shift)" block
    # from: "# --- Monthly insights (per-shift) ---" down to "top_noshow = ..."

    # --- Monthly insights (per-shift, supports long shifts) ---
    month_shifts = list(
        ShiftAssignment.objects.filter(
            date__gte=month_start, date__lt=month_end,
            status="APPROVED",
        ).select_related("employee")
    )

    month_leaves = list(
        LeaveRequest.objects.filter(
            status="APPROVED",
            date_from__lt=month_end,
            date_to__gte=month_start,
        ).values("employee_id", "date_from", "date_to")
    )

    def is_on_leave(emp_id, d):
        for lv in month_leaves:
            if lv["employee_id"] == emp_id and lv["date_from"] <= d <= lv["date_to"]:
                return True
        return False

    # sessions in month for matching + open sessions (for long shift coverage)
    month_start_dt = timezone.make_aware(datetime.combine(month_start, datetime.min.time()))
    month_end_dt = timezone.make_aware(datetime.combine(month_end, datetime.min.time()))
    month_sessions = list(
        AttendanceSession.objects.filter(
            clock_in_time__gte=month_start_dt,
            clock_in_time__lt=month_end_dt
        )
        .select_related("employee")
        .order_by("clock_in_time")
    )

    # ✅ include open sessions that started before month_end but still open now
    open_sessions_month = list(
        AttendanceSession.objects.filter(
            is_open=True,
            clock_in_time__lt=month_end_dt,
        ).select_related("employee")
    )

    # Map: (employee_id, date) -> sessions relevant to that date
    # We add sessions keyed by their IN date, and for open sessions also include them for every date they could cover.
    month_sessions_by_emp_date = {}
    for s in month_sessions:
        d = timezone.localtime(s.clock_in_time).date()
        month_sessions_by_emp_date.setdefault((s.employee_id, d), []).append(s)

    # For open sessions, they may cover multiple days (but you said no overnight shifts).
    # Still, this makes it robust if someone forgets to OUT close to midnight.
    now_dt = timezone.now()
    for s in open_sessions_month:
        in_date = timezone.localtime(s.clock_in_time).date()
        # clamp within month bounds
        cur = max(in_date, month_start)
        last = min(now_dt.date(), (month_end - timedelta(days=1)))
        while cur <= last:
            month_sessions_by_emp_date.setdefault((s.employee_id, cur), []).append(s)
            cur += timedelta(days=1)

    # Ensure deterministic ordering
    for k in month_sessions_by_emp_date:
        month_sessions_by_emp_date[k] = sorted(
            month_sessions_by_emp_date[k],
            key=lambda x: x.clock_in_time or month_start_dt
        )

    m_scheduled = m_attended = m_ontime = m_late = m_noshow = 0
    per_emp = {}  # emp_id -> counters

    for sh in month_shifts:
        if is_on_leave(sh.employee_id, sh.date):
            continue

        m_scheduled += 1

        shift_start_dt = dt_combine(sh.date, sh.start_time)
        shift_end_dt = dt_combine(sh.date, sh.end_time)

        window_start = shift_start_dt - timedelta(minutes=EARLY_WINDOW_MINUTES)
        window_end = shift_start_dt + timedelta(minutes=NO_SHOW_MINUTES)

        emp_day_sessions = month_sessions_by_emp_date.get((sh.employee_id, sh.date), [])

        # 1) punctuality (per-shift IN near shift start)
        matched_in = None
        for sess in emp_day_sessions:
            if sess.clock_in_time and window_start <= sess.clock_in_time <= window_end:
                matched_in = sess.clock_in_time
                break

        # 2) coverage (long shift): any session overlaps shift interval
        covered = any(session_overlaps_shift(sess, shift_start_dt, shift_end_dt, now_dt) for sess in emp_day_sessions)

        stats = per_emp.setdefault(
            sh.employee_id,
            {"emp": sh.employee, "scheduled": 0, "attended": 0, "late": 0, "noshow": 0}
        )
        stats["scheduled"] += 1

        if not covered:
            m_noshow += 1
            stats["noshow"] += 1
            continue

        # covered => attended
        m_attended += 1
        stats["attended"] += 1

        if matched_in is None:
            # Covered by a long session but no fresh IN near this shift start.
            # Count as on-time for rate purposes (same policy as today).
            m_ontime += 1
            continue

        diff_min = int((matched_in - shift_start_dt).total_seconds() // 60)
        minutes_late = max(0, diff_min)
        if minutes_late <= GRACE_MINUTES:
            m_ontime += 1
        else:
            m_late += 1
            stats["late"] += 1

    monthly_att_rate = round((m_attended / m_scheduled) * 100, 1) if m_scheduled else 0.0
    monthly_late_rate = round((m_late / m_scheduled) * 100, 1) if m_scheduled else 0.0
    monthly_ontime_rate = round((m_ontime / m_scheduled) * 100, 1) if m_scheduled else 0.0

    top_late = sorted(per_emp.values(), key=lambda x: (x["late"], x["noshow"]), reverse=True)[:5]
    top_noshow = sorted(per_emp.values(), key=lambda x: x["noshow"], reverse=True)[:5]

    context = {
        "today": today,

        # operational KPIs
        "scheduled_shifts": scheduled,
        "attended_shifts": attended,
        "attendance_rate": attendance_rate,
        "on_time_shifts": on_time,
        "late_shifts": late,
        "no_show_shifts": no_show,
        "on_time_rate": on_time_rate,
        "late_rate": late_rate,
        "week_start": week_start,
        "pending_rosters": pending_rosters,
        # exceptions
        "punctual_rows": punctual_rows,
        "open_sessions": open_sessions,
        "open_too_long": open_too_long,

        # audit trail
        "today_events": today_events_qs[:200],
        "today_count": today_events_qs.count(),
        "proxy_events_count": proxy_events_qs.count(),
        "covered_shifts": covered_only,

        # monthly
        "month_start": month_start,
        "monthly_scheduled": m_scheduled,
        "monthly_att_rate": monthly_att_rate,
        "monthly_ontime_rate": monthly_ontime_rate,
        "monthly_late_rate": monthly_late_rate,
        "top_late": top_late,
        "top_noshow": top_noshow,
    }
    return render(request, "attendance/manager_dashboard.html", context)


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
        # For each employee/day, we receive multi-select list: shifts_<empid>_<date> = [template_id, template_id...]
        # We'll replace the day’s assignments entirely (delete then recreate).
        for emp in employees:
            for d in days:
                key = f"shifts_{emp.id}_{d.isoformat()}"
                selected_template_ids = request.POST.getlist(key)  # can be []

                # delete all existing for that emp/day (within this division)
                ShiftAssignment.objects.filter(employee=emp, division=division, date=d).delete()

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
