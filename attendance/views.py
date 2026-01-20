from datetime import timedelta
import os
from io import BytesIO
from django.core.files.base import ContentFile
from PIL import Image, ImageOps

from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_GET

from .models import Employee, AttendanceSession, AttendanceEvent
from .qr import make_qr_token, window_meta, validate_qr_token, token_expires_in

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


@login_required
@user_passes_test(is_manager)
def manager_dashboard(request):
    today = timezone.localdate()
    start = timezone.make_aware(timezone.datetime.combine(today, timezone.datetime.min.time()))
    end = start + timedelta(days=1)

    open_sessions = AttendanceSession.objects.filter(is_open=True).select_related("employee").order_by("clock_in_time")

    today_events = (AttendanceEvent.objects
                    .filter(created_at__gte=start, created_at__lt=end)
                    .select_related("subject_employee", "witness_employee", "session")
                    .order_by("-created_at")
                    )

    proxy_events = today_events.filter(is_proxy=True)

    context = {
        "open_sessions": open_sessions,
        "today_events": today_events[:200],  # limit for speed
        "proxy_events_count": proxy_events.count(),
        "today_count": today_events.count(),
        "today": today,
    }
    return render(request, "attendance/manager_dashboard.html", context)
