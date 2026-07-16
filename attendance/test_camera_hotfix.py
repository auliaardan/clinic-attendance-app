from django.test import TestCase
from django.urls import reverse

from .qr import make_qr_token


class CameraAndQrHotfixTests(TestCase):
    def test_qr_image_endpoint_renders_png_for_valid_token(self):
        response = self.client.get(reverse("qr_image"), {"token": make_qr_token()})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(response.content[:8], b"\x89PNG\r\n\x1a\n")
        self.assertIn("no-store", response["Cache-Control"])

    def test_qr_image_endpoint_rejects_invalid_token(self):
        response = self.client.get(reverse("qr_image"), {"token": "not-valid"})
        self.assertEqual(response.status_code, 403)

    def test_display_uses_server_rendered_qr_without_qrcodejs_cdn(self):
        response = self.client.get(reverse("qr_display"))
        self.assertContains(response, reverse("qr_image"))
        self.assertNotContains(response, "qrcodejs")
        self.assertNotContains(response, "qrcode.min.js")

    def test_attendance_uses_sequential_camera_workflow(self):
        response = self.client.get(reverse("attendance_page"))
        self.assertContains(response, "BarcodeDetector")
        self.assertContains(response, 'capture="user"')
        self.assertContains(response, "stopQrScanner")
        self.assertNotContains(response, "startSelfieCamera")
        self.assertNotContains(response, "getUserMedia({video: {facingMode: \"user\"}")
