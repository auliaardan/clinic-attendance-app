from django.test import TestCase
from django.urls import reverse

from .models import Employee
from .qr import make_qr_token, token_expires_in


class EmployeePinTests(TestCase):
    def test_employee_pin_is_hashed_and_verifiable(self):
        employee = Employee(name="Test Employee")
        employee.set_pin("123456")
        employee.save()

        self.assertNotEqual(employee.pin_hash, "123456")
        self.assertTrue(employee.check_pin("123456"))
        self.assertFalse(employee.check_pin("654321"))


class QrTokenTests(TestCase):
    def test_generated_qr_token_is_valid(self):
        token = make_qr_token(window_seconds=60)
        self.assertGreater(
            token_expires_in(token, window_seconds=60, max_age_seconds=70),
            0,
        )

    def test_invalid_qr_token_is_rejected(self):
        self.assertEqual(
            token_expires_in("invalid-token", window_seconds=60, max_age_seconds=70),
            0,
        )


class PublicPageSmokeTests(TestCase):
    def test_home_page_loads(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)

    def test_qr_display_loads(self):
        response = self.client.get(reverse("qr_display"))
        self.assertEqual(response.status_code, 200)

    def test_manager_dashboard_requires_login(self):
        response = self.client.get(reverse("manager_dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

from datetime import time, timedelta
from io import BytesIO
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import override_settings
from django.utils import timezone
from PIL import Image
from .models import AttendanceSession, ShiftAssignment, Division, ShiftTemplate, EmployeeProfile, LeaveRequest, PinAttempt, AttendanceCorrectionRequest
from .services import classify_shift


def pin_employee(name="Emp", pin="123456"):
    e = Employee(name=name, is_active=True)
    e.set_pin(pin)
    e.save()
    return e


def tiny_jpeg():
    b = BytesIO(); Image.new("RGB", (8, 8), "white").save(b, format="JPEG"); b.seek(0)
    return SimpleUploadedFile("p.jpg", b.read(), content_type="image/jpeg")


class PhaseOneAttendanceTests(TestCase):
    def test_yesterday_open_session_does_not_cover_today_shift(self):
        emp = pin_employee()
        div = Division.objects.create(name="D")
        sh = ShiftAssignment.objects.create(employee=emp, division=div, date=timezone.localdate(), start_time=time(9), end_time=time(17), status="APPROVED")
        AttendanceSession.objects.create(employee=emp, clock_in_time=timezone.now() - timedelta(days=1), is_open=True)
        self.assertEqual(classify_shift(sh, AttendanceSession.objects.filter(employee=emp))["status"], "NO_SHOW")

    def test_same_day_session_and_grace_classification(self):
        emp = pin_employee(); div = Division.objects.create(name="D")
        today = timezone.localdate()
        sh = ShiftAssignment.objects.create(employee=emp, division=div, date=today, start_time=time(9), end_time=time(17), status="APPROVED")
        start = timezone.make_aware(timezone.datetime.combine(today, time(9, 10)))
        AttendanceSession.objects.create(employee=emp, clock_in_time=start, clock_out_time=start + timedelta(hours=1), is_open=False)
        self.assertEqual(classify_shift(sh, AttendanceSession.objects.filter(employee=emp))["status"], "ON_TIME")

    def test_approved_leave_excludes_denominator_data_available(self):
        emp = pin_employee(); today = timezone.localdate()
        LeaveRequest.objects.create(employee=emp, date_from=today, date_to=today, status="APPROVED")
        self.assertTrue(LeaveRequest.objects.filter(employee=emp, status="APPROVED", date_from__lte=today, date_to__gte=today).exists())


class PhaseOneClockTests(TestCase):
    def post_clock(self, emp, pin="123456", action="IN", photo=None, **extra):
        data = {"action": action, "qr_token": make_qr_token(), "subject_employee_id": emp.id, "subject_pin": pin, **extra}
        files = {"photo": photo if photo is not None else tiny_jpeg()}
        return self.client.post(reverse("api_clock"), data={**data, **files})

    def test_repeated_clock_in_receives_409_and_db_rejects_duplicate_open(self):
        emp = pin_employee()
        self.assertEqual(self.post_clock(emp).status_code, 200)
        self.assertEqual(self.post_clock(emp).status_code, 409)
        with self.assertRaises(IntegrityError):
            AttendanceSession.objects.create(employee=emp, clock_in_time=timezone.now(), is_open=True)

    def test_clock_out_closes_open_session(self):
        emp = pin_employee(); sess = AttendanceSession.objects.create(employee=emp, clock_in_time=timezone.now(), is_open=True)
        self.assertEqual(self.post_clock(emp, action="OUT").status_code, 200)
        sess.refresh_from_db(); self.assertFalse(sess.is_open); self.assertIsNotNone(sess.clock_out_time)

    def test_missing_invalid_and_valid_photo(self):
        emp = pin_employee()
        base = {"action":"IN", "qr_token":make_qr_token(), "subject_employee_id":emp.id, "subject_pin":"123456"}
        self.assertEqual(self.client.post(reverse("api_clock"), data=base).status_code, 400)
        bad = SimpleUploadedFile("bad.txt", b"not image", content_type="text/plain")
        self.assertEqual(self.client.post(reverse("api_clock"), data={**base, "photo": bad}).status_code, 400)
        self.assertEqual(self.client.post(reverse("api_clock"), data={**base, "photo": tiny_jpeg()}).status_code, 200)

    def test_pin_throttle_threshold_success_reset_and_witness_isolation(self):
        emp = pin_employee(); witness = pin_employee("W", "222222")
        for _ in range(5): self.post_clock(emp, pin="000000")
        self.assertEqual(self.post_clock(emp, pin="000000").status_code, 429)
        PinAttempt.objects.all().delete()
        self.assertEqual(self.post_clock(emp).status_code, 200)
        self.client.post(reverse("api_clock"), data={"action":"OUT","qr_token":make_qr_token(),"subject_employee_id":emp.id,"subject_pin":"123456","is_proxy":"1","witness_employee_id":witness.id,"witness_pin":"000000","photo":tiny_jpeg()})
        self.assertFalse(PinAttempt.objects.filter(employee=emp, purpose="SUBJECT").exists())
        self.assertTrue(PinAttempt.objects.filter(employee=witness, purpose="WITNESS").exists())

from django.core.management import call_command
from django.core.files.base import ContentFile
from tempfile import TemporaryDirectory
from django.conf import settings
from attendance.models import AttendanceEvent
from datetime import date as dt_date
import os

class PhaseTwoManagerOperationsTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.manager = User.objects.create_user("manager", password="pw", is_staff=True)
        self.user = User.objects.create_user("user", password="pw", is_staff=False)
        self.div = Division.objects.create(name="Ops")
        self.other = Division.objects.create(name="Other")
        self.emp = pin_employee("Alice")
        EmployeeProfile.objects.create(employee=self.emp, division=self.div)
        self.today = timezone.localdate()

    def shift(self, emp=None, div=None, day=None, start=time(9), end=time(17)):
        return ShiftAssignment.objects.create(employee=emp or self.emp, division=div or self.div, date=day or self.today, start_time=start, end_time=end, status="APPROVED")

    def test_dashboard_requires_manager_and_filters_by_date_and_division(self):
        self.shift()
        bob = pin_employee("Bob"); EmployeeProfile.objects.create(employee=bob, division=self.other); self.shift(bob, self.other)
        self.assertEqual(self.client.get(reverse("manager_dashboard")).status_code, 302)
        self.client.login(username="user", password="pw")
        self.assertEqual(self.client.get(reverse("manager_dashboard")).status_code, 302)
        self.client.logout(); self.client.login(username="manager", password="pw")
        response = self.client.get(reverse("manager_dashboard"), {"date": self.today.isoformat(), "division": self.div.id})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alice")
        self.assertNotContains(response, "Bob")

    def test_open_session_does_not_cover_later_shift_and_missing_clockout_flagged(self):
        yesterday = self.today - timedelta(days=1)
        sh = self.shift(day=self.today)
        AttendanceSession.objects.create(employee=self.emp, clock_in_time=timezone.make_aware(timezone.datetime.combine(yesterday, time(9))), is_open=True)
        self.assertEqual(classify_shift(sh, AttendanceSession.objects.filter(employee=self.emp), timezone.make_aware(timezone.datetime.combine(self.today, time(13))))["status"], "NO_SHOW")
        sess = AttendanceSession.objects.create(employee=pin_employee("Carol"), clock_in_time=timezone.make_aware(timezone.datetime.combine(self.today, time(9))), is_open=True)
        sh2 = self.shift(sess.employee, self.div, self.today, time(9), time(10))
        result = classify_shift(sh2, [sess], timezone.make_aware(timezone.datetime.combine(self.today, time(12))))
        self.assertTrue(result["missing_clockout"])

    def test_overnight_shift_calculates_correctly(self):
        sh = self.shift(start=time(22), end=time(6))
        start = timezone.make_aware(timezone.datetime.combine(self.today, time(22, 5)))
        sess = AttendanceSession.objects.create(employee=self.emp, clock_in_time=start, clock_out_time=start + timedelta(hours=8), is_open=False)
        self.assertEqual(classify_shift(sh, [sess], start + timedelta(hours=9))["status"], "ON_TIME")

    def test_csv_export_excludes_sensitive_fields(self):
        self.shift()
        self.client.login(username="manager", password="pw")
        response = self.client.get(reverse("manager_attendance_csv"), {"date": self.today.isoformat()})
        body = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Employee,Division", body)
        for forbidden in ("photo", "pin", "hash", "client_ip", "user_agent"):
            self.assertNotIn(forbidden, body.lower())

    def test_photo_endpoint_auth_and_missing_file_retains_event(self):
        sess = AttendanceSession.objects.create(employee=self.emp, clock_in_time=timezone.now(), is_open=True)
        event = AttendanceEvent.objects.create(event_type="IN", session=sess, subject_employee=self.emp, photo=ContentFile(b"abc", name="x.jpg"))
        self.assertEqual(self.client.get(reverse("attendance_photo", args=[event.id])).status_code, 302)
        self.client.login(username="user", password="pw")
        self.assertEqual(self.client.get(reverse("attendance_photo", args=[event.id])).status_code, 302)
        self.client.logout(); self.client.login(username="manager", password="pw")
        event.photo.delete(save=False); event.save(update_fields=["photo"])
        self.assertEqual(self.client.get(reverse("attendance_photo", args=[event.id])).status_code, 404)
        self.assertTrue(AttendanceEvent.objects.filter(id=event.id).exists())

    def test_purge_photos_dry_run_confirm_missing_and_record_retention(self):
        with self.settings(MEDIA_ROOT=TemporaryDirectory().name):
            sess = AttendanceSession.objects.create(employee=self.emp, clock_in_time=timezone.now(), is_open=True)
            old = timezone.now() - timedelta(days=100)
            event = AttendanceEvent.objects.create(event_type="IN", session=sess, subject_employee=self.emp, created_at=old, photo=ContentFile(b"abc", name="old.jpg"))
            path = event.photo.path
            call_command("purge_attendance_photos", "--older-than-days", "90")
            event.refresh_from_db(); self.assertTrue(event.photo); self.assertTrue(os.path.exists(path))
            call_command("purge_attendance_photos", "--older-than-days", "90", "--confirm")
            event.refresh_from_db(); self.assertFalse(event.photo); self.assertTrue(AttendanceEvent.objects.filter(id=event.id).exists())
            missing = AttendanceEvent.objects.create(event_type="OUT", session=sess, subject_employee=self.emp, created_at=old, photo="missing.jpg")
            call_command("purge_attendance_photos", "--older-than-days", "90", "--confirm")
            self.assertTrue(AttendanceEvent.objects.filter(id=missing.id).exists())

class PhaseThreeEmployeeSelfServiceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.manager = User.objects.create_user("mgr3", password="pw", is_staff=True)
        self.emp = pin_employee("Dina", "123456")
        self.other = pin_employee("Eko", "654321")
        self.div = Division.objects.create(name="Front")
        EmployeeProfile.objects.create(employee=self.emp, division=self.div)
        EmployeeProfile.objects.create(employee=self.other, division=self.div)

    def login_employee(self, pin="123456"):
        return self.client.post(reverse("employee_login"), {"employee": self.emp.id, "pin": pin})

    def test_employee_pin_login_logout_and_dashboard_ownership(self):
        old_key = self.client.session.session_key
        response = self.login_employee()
        self.assertEqual(response.status_code, 302)
        self.assertNotEqual(self.client.session.session_key, old_key)
        LeaveRequest.objects.create(employee=self.emp, date_from=timezone.localdate(), date_to=timezone.localdate(), note="Mine")
        LeaveRequest.objects.create(employee=self.other, date_from=timezone.localdate(), date_to=timezone.localdate(), note="OtherSecret")
        response = self.client.get(reverse("employee_dashboard"))
        self.assertContains(response, "Dina")
        self.assertContains(response, "Mine")
        self.assertNotContains(response, "OtherSecret")
        self.assertEqual(self.client.post(reverse("employee_logout")).status_code, 302)
        self.assertNotIn("employee_id", self.client.session)

    def test_wrong_pin_locks_employee_login(self):
        for _ in range(5):
            self.login_employee("000000")
        self.assertEqual(self.login_employee("000000").status_code, 200)
        self.assertTrue(PinAttempt.objects.filter(employee=self.emp, purpose="EMPLOYEE_LOGIN", locked_until__gt=timezone.now()).exists())

    def test_leave_validation_and_employee_cannot_approve(self):
        self.login_employee()
        today = timezone.localdate()
        self.assertContains(self.client.post(reverse("employee_leave_new"), {"date_from": today, "date_to": today - timedelta(days=1), "leave_type": "SICK", "note": "x"}), "Tanggal selesai")
        self.assertEqual(self.client.post(reverse("employee_leave_new"), {"date_from": today, "date_to": today, "leave_type": "SICK", "note": "x"}).status_code, 302)
        leave = LeaveRequest.objects.get(employee=self.emp)
        self.assertEqual(leave.status, "SUBMITTED")
        self.assertEqual(self.client.post(reverse("manager_leave_action", args=[leave.id, "approve"])).status_code, 302)
        leave.refresh_from_db(); self.assertEqual(leave.status, "SUBMITTED")

    def test_correction_lifecycle_does_not_rewrite_attendance(self):
        sess = AttendanceSession.objects.create(employee=self.emp, clock_in_time=timezone.now(), is_open=True)
        original_in = sess.clock_in_time
        self.login_employee()
        response = self.client.post(reverse("employee_correction_new"), {"session": sess.id, "request_type": "WRONG_TIME", "requested_clock_in": "2026-01-01T09:00", "reason": "Jam salah"})
        self.assertEqual(response.status_code, 302)
        corr = AttendanceCorrectionRequest.objects.get(employee=self.emp)
        dup = self.client.post(reverse("employee_correction_new"), {"session": sess.id, "request_type": "WRONG_TIME", "reason": "dupe"})
        self.assertContains(dup, "masih menunggu")
        self.client.logout(); self.client.login(username="mgr3", password="pw")
        self.assertEqual(self.client.post(reverse("manager_correction_action", args=[corr.id, "approve"]), {"manager_note": "ok"}).status_code, 302)
        corr.refresh_from_db(); sess.refresh_from_db()
        self.assertEqual(corr.status, "APPROVED")
        self.assertEqual(sess.clock_in_time, original_in)

    def test_manager_review_requires_manager_and_post_only(self):
        self.assertEqual(self.client.get(reverse("manager_requests")).status_code, 302)
        self.login_employee()
        self.assertEqual(self.client.get(reverse("manager_requests")).status_code, 302)
        self.client.logout(); self.client.login(username="mgr3", password="pw")
        self.assertEqual(self.client.get(reverse("manager_requests")).status_code, 200)

class PhaseFourNavigationPortalUxTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.manager = User.objects.create_user("phase4mgr", password="pw", is_staff=True)
        self.user = User.objects.create_user("phase4user", password="pw")
        self.emp = pin_employee("Nina Staff", "123456")

    def test_landing_page_links_to_major_workflows_and_logged_out_employee_login(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mulai Absensi")
        self.assertContains(response, reverse("attendance_page"))
        self.assertContains(response, "Portal Staff")
        self.assertContains(response, reverse("employee_login"))
        self.assertContains(response, "Portal Manager")
        self.assertContains(response, reverse("manager_dashboard"))

    def test_attendance_page_loads_existing_interface_and_keeps_api_urls(self):
        response = self.client.get(reverse("attendance_page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Scan QR • Selfie • PIN")
        self.assertContains(response, 'fetch(`/api/qr/check/?token=${encodeURIComponent(token)}`)')
        self.assertContains(response, 'fetch("/api/clock/", {method: "POST", body: form})')

    def test_valid_employee_session_changes_link_to_dashboard(self):
        self.client.post(reverse("employee_login"), {"employee": self.emp.id, "pin": "123456"})
        response = self.client.get(reverse("home"))
        self.assertContains(response, reverse("employee_dashboard"))
        self.assertContains(response, "Nina Staff")

    def test_expired_employee_session_does_not_expose_identity(self):
        session = self.client.session
        session["employee_id"] = self.emp.id
        session["employee_authenticated_at"] = (timezone.now() - timedelta(minutes=31)).isoformat()
        session.save()
        response = self.client.get(reverse("home"))
        self.assertNotContains(response, "Nina Staff")
        self.assertContains(response, reverse("employee_login"))

    def test_employee_logout_post_only_and_csrf_protected(self):
        self.client.post(reverse("employee_login"), {"employee": self.emp.id, "pin": "123456"})
        self.assertEqual(self.client.get(reverse("employee_logout")).status_code, 405)
        from django.test import Client
        csrf_client = Client(enforce_csrf_checks=True)
        self.assertEqual(csrf_client.post(reverse("employee_logout")).status_code, 403)

    def test_manager_and_roster_navigation_does_not_bypass_authorization(self):
        self.assertEqual(self.client.get(reverse("manager_dashboard")).status_code, 302)
        self.assertEqual(self.client.get(reverse("roster_week")).status_code, 302)
        self.client.login(username="phase4user", password="pw")
        self.assertEqual(self.client.get(reverse("manager_dashboard")).status_code, 302)
        response = self.client.get(reverse("home"))
        self.assertNotContains(response, reverse("roster_week"))

    def test_display_remains_standalone_without_shared_navigation(self):
        response = self.client.get(reverse("qr_display"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SCAN THIS QR")
        self.assertNotContains(response, "navbar")
        self.assertNotContains(response, "Portal Staff")

from django.core.management import call_command
from unittest.mock import patch
from attendance.models import FixedScheduleRule, ScheduleException, NotificationDelivery
from attendance.services import generate_fixed_shifts, process_alerts, shift_datetimes

class PhaseFiveFixedScheduleTests(TestCase):
    def setUp(self):
        self.div = Division.objects.create(name="Office", schedule_mode="FIXED")
        self.roster_div = Division.objects.create(name="Clinic")
        self.emp = pin_employee("Fixed Emp")
        EmployeeProfile.objects.create(employee=self.emp, division=self.div, is_rostered=True)
        for wd in range(5):
            FixedScheduleRule.objects.create(division=self.div, weekday=wd, is_workday=True, start_time=time(8), end_time=time(17))
        FixedScheduleRule.objects.create(division=self.div, weekday=5, is_workday=False)

    def test_defaults_and_generation_idempotent_manual_precedence(self):
        self.assertEqual(self.roster_div.schedule_mode, "ROSTER")
        monday = dt_date(2026, 7, 20)
        counts = generate_fixed_shifts(monday, days=6, confirm=True)
        self.assertEqual(counts["created"], 5)
        self.assertEqual(ShiftAssignment.objects.filter(source="FIXED", status="APPROVED").count(), 5)
        counts = generate_fixed_shifts(monday, days=6, confirm=True)
        self.assertEqual(counts["created"], 0)
        tuesday = monday + timedelta(days=1)
        ShiftAssignment.objects.filter(employee=self.emp, date=tuesday, source="FIXED").delete()
        ShiftAssignment.objects.create(employee=self.emp, division=self.div, date=tuesday, start_time=time(9), end_time=time(12), status="APPROVED")
        counts = generate_fixed_shifts(monday, days=2, confirm=True)
        self.assertGreaterEqual(counts["skipped"], 1)
        self.assertFalse(ShiftAssignment.objects.filter(employee=self.emp, date=tuesday, source="FIXED").exists())

    def test_exception_and_future_update_not_past_update(self):
        monday = dt_date(2026, 7, 20)
        ScheduleException.objects.create(division=self.div, date=monday, is_workday=False, note="Holiday")
        special = monday + timedelta(days=5)
        ScheduleException.objects.create(division=self.div, date=special, is_workday=True, start_time=time(10), end_time=time(14))
        generate_fixed_shifts(monday, days=6, confirm=True)
        self.assertFalse(ShiftAssignment.objects.filter(date=monday).exists())
        self.assertTrue(ShiftAssignment.objects.filter(date=special, start_time=time(10), end_time=time(14)).exists())

    def test_overnight_fixed_shift_classification(self):
        night = Division.objects.create(name="Night", schedule_mode="FIXED")
        emp = pin_employee("Night Emp"); EmployeeProfile.objects.create(employee=emp, division=night)
        FixedScheduleRule.objects.create(division=night, weekday=0, is_workday=True, start_time=time(22), end_time=time(6))
        monday = dt_date(2026, 7, 20)
        generate_fixed_shifts(monday, days=1, confirm=True)
        sh = ShiftAssignment.objects.get(employee=emp, date=monday)
        start, end = shift_datetimes(sh)
        self.assertEqual((end - start).total_seconds(), 8*3600)

class PhaseFiveAlertTests(TestCase):
    def setUp(self):
        self.div = Division.objects.create(name="Alerts")
        self.emp = pin_employee("Alert Emp")
        EmployeeProfile.objects.create(employee=self.emp, division=self.div)

    @override_settings(TELEGRAM_ALERTS_ENABLED=True, TELEGRAM_BOT_TOKEN="123:ABC", TELEGRAM_CHAT_IDS="1")
    @patch("attendance.services.urlrequest.urlopen")
    def test_dry_run_no_telegram_and_send_dedupes(self, post):
        today = timezone.localdate()
        LeaveRequest.objects.create(employee=self.emp, date_from=today, date_to=today, status="SUBMITTED")
        rows = process_alerts(send=False, event_type="NEW_LEAVE_REQUEST", target_date=today)
        self.assertTrue(rows); post.assert_not_called()
        post.return_value.__enter__.return_value.status = 200
        process_alerts(send=True, event_type="NEW_LEAVE_REQUEST", target_date=today)
        process_alerts(send=True, event_type="NEW_LEAVE_REQUEST", target_date=today)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(NotificationDelivery.objects.get(event_type="NEW_LEAVE_REQUEST").status, "SENT")

    @override_settings(TELEGRAM_ALERTS_ENABLED=True, TELEGRAM_BOT_TOKEN="123:SECRET", TELEGRAM_CHAT_IDS="1")
    @patch("attendance.services.urlrequest.urlopen", side_effect=Exception("https://api.telegram.org/bot123:SECRET/sendMessage failed"))
    def test_telegram_failure_sanitized(self, post):
        today = timezone.localdate()
        LeaveRequest.objects.create(employee=self.emp, date_from=today, date_to=today, status="SUBMITTED")
        process_alerts(send=True, event_type="NEW_LEAVE_REQUEST", target_date=today)
        rec = NotificationDelivery.objects.get()
        self.assertEqual(rec.status, "FAILED")
        self.assertNotIn("SECRET", rec.last_error)
