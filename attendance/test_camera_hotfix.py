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

    def test_qr_png_encodes_absolute_attendance_url(self):
        from attendance import qr_views

        source = open(qr_views.__file__, encoding="utf-8").read()
        self.assertIn("request.build_absolute_uri", source)
        self.assertIn("reverse('attendance_page')", source)
        self.assertIn("urlencode({'qr': token})", source)

    def test_attendance_supports_android_and_iphone_inline_scanning(self):
        response = self.client.get(reverse("attendance_page"))
        self.assertContains(response, "BarcodeDetector")
        self.assertContains(response, "jsQR")
        self.assertContains(response, "scanWithJsQr")
        self.assertContains(response, "Scanner bekerja langsung di Android dan iPhone")
        self.assertContains(response, 'capture="user"')
        self.assertContains(response, "stopQrScanner")
        self.assertContains(response, 'new URLSearchParams(location.search).get("qr")')
        self.assertNotContains(response, "gunakan aplikasi Camera")
        self.assertNotContains(response, "startSelfieCamera")
