import time
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired

signer = TimestampSigner(salt="clinic-attendance-qr")

def make_qr_token(window_seconds=60) -> str:
    # Signed payload changes every window (minute)
    window = int(time.time() // window_seconds)
    payload = f"qrwin:{window}"
    return signer.sign(payload)

def window_meta(window_seconds=60):
    now = time.time()
    # end of current window boundary, server-time
    end = (int(now // window_seconds) + 1) * window_seconds
    expires_in = max(0, int(end - now))
    return {
        "server_now": int(now),
        "expires_at": int(end),
        "expires_in": expires_in,
        "window_seconds": window_seconds,
    }

def validate_qr_token(token: str, max_age_seconds=70) -> bool:
    try:
        signer.unsign(token, max_age=max_age_seconds)
        return True
    except (BadSignature, SignatureExpired):
        return False

def token_expires_in(token: str, window_seconds=60, max_age_seconds=70) -> int:
    """
    Returns seconds left until the current server window ends IF token is valid.
    If invalid/expired -> 0
    """
    if not validate_qr_token(token, max_age_seconds=max_age_seconds):
        return 0
    meta = window_meta(window_seconds=window_seconds)
    return meta["expires_in"]
