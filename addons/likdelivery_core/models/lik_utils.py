import secrets


def generate_code(prefix="", length=8):
    """Exact port of models.py generate_code (LK-ORD-01, LK-PAY-02)."""
    return prefix + secrets.token_hex(length // 2).upper()[:length]


def generate_otp():
    """6 uppercase hex chars (LK-ORD-01, LK-MSN-06)."""
    return secrets.token_hex(3).upper()


def generate_qr_token():
    """LK-MSN-06."""
    return secrets.token_urlsafe(32)
