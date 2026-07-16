from io import BytesIO
from urllib.parse import urlencode

import qrcode
from django.http import HttpResponse
from django.urls import reverse
from django.views.decorators.http import require_GET

from .qr import token_expires_in


@require_GET
def qr_image(request):
    """Render a valid rotating attendance URL as a PNG without browser CDN dependencies."""
    token = (request.GET.get("token") or "").strip()
    if token_expires_in(token, window_seconds=60, max_age_seconds=70) <= 0:
        return HttpResponse("Expired or invalid QR token", status=403, content_type="text/plain")

    attendance_path = f"{reverse('attendance_page')}?{urlencode({'qr': token})}"
    attendance_url = request.build_absolute_uri(attendance_path)

    image = qrcode.make(attendance_url)
    output = BytesIO()
    image.save(output, format="PNG")
    response = HttpResponse(output.getvalue(), content_type="image/png")
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    return response
