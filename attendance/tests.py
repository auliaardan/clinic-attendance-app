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
