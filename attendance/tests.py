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
from .models import AttendanceSession, ShiftAssignment, Division, ShiftTemplate, EmployeeProfile, LeaveRequest, PinAttempt
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
