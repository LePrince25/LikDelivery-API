import secrets
from datetime import datetime, timedelta

import jwt

from odoo.http import request

from .envelope import (
    AUTH_EXPIRED,
    AUTH_INVALID,
    ApiError,
    anti_enumeration_delay,
    raise_error,
)

ACCESS_TTL_SECONDS = 3600  # 1 h
REFRESH_TTL_DAYS = 30
ACCESS_COOKIE = "lik_token"
REFRESH_COOKIE = "lik_refresh"


def _secret():
    icp = request.env["ir.config_parameter"].sudo()
    secret = icp.get_param("likdelivery_api.jwt_secret")
    if not secret:
        secret = secrets.token_hex(32)
        icp.set_param("likdelivery_api.jwt_secret", secret)
    return secret


def _encode(payload):
    return jwt.encode(payload, _secret(), algorithm="HS256")


def _decode(token):
    try:
        return jwt.decode(token, _secret(), algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise_error(AUTH_EXPIRED, "Jeton expire")
    except jwt.InvalidTokenError:
        raise_error(AUTH_INVALID, "Jeton invalide")


def issue_tokens(user):
    """Access (1 h) + rotating refresh (30 d). jti stored on the user for
    revocation / reuse detection (LK-AUT-04)."""
    now = datetime.utcnow()
    jti = secrets.token_hex(16)
    access = _encode(
        {
            "sub": str(user.id),
            "role": user.lik_role,
            "typ": "access",
            "iat": now,
            "exp": now + timedelta(seconds=ACCESS_TTL_SECONDS),
        }
    )
    refresh = _encode(
        {
            "sub": str(user.id),
            "jti": jti,
            "typ": "refresh",
            "iat": now,
            "exp": now + timedelta(days=REFRESH_TTL_DAYS),
        }
    )
    user.sudo().lik_jwt_jti = jti
    return access, refresh


def rotate_tokens(refresh_token):
    """Verify + rotate a refresh token. Reuse of a revoked/old token is
    rejected (jti mismatch)."""
    payload = _decode(refresh_token)
    if payload.get("typ") != "refresh":
        raise_error(AUTH_INVALID, "Jeton invalide")
    user = request.env["likdelivery.user"].sudo().browse(int(payload["sub"]))
    if not user.exists() or not user.active:
        anti_enumeration_delay()
        raise_error(AUTH_INVALID, "Jeton invalide")
    if payload.get("jti") != user.lik_jwt_jti:
        anti_enumeration_delay()
        raise_error(AUTH_INVALID, "Jeton revoque")
    return user, *issue_tokens(user)


def revoke(user):
    user.sudo().lik_jwt_jti = False


def _bearer_token():
    header = request.httprequest.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:].strip()
    return None


def authenticate():
    """Dual mode: Bearer header first, HttpOnly cookie fallback (LK-AUT-04).

    Attaches and returns the likdelivery.user. Raises 401 otherwise.
    """
    token = _bearer_token() or request.httprequest.cookies.get(ACCESS_COOKIE)
    if not token:
        raise_error(AUTH_INVALID, "Non authentifie")
    payload = _decode(token)
    if payload.get("typ") != "access":
        raise_error(AUTH_INVALID, "Jeton invalide")
    user = request.env["likdelivery.user"].sudo().browse(int(payload["sub"]))
    if not user.exists() or not user.active:
        anti_enumeration_delay()
        raise_error(AUTH_INVALID, "Non authentifie")
    request.lik_user = user
    return user


def auth_cookies(access, refresh):
    """HttpOnly cookie transport for the PWA (SameSite=Lax)."""
    return [
        (
            ACCESS_COOKIE,
            access,
            {"max_age": ACCESS_TTL_SECONDS, "httponly": True, "samesite": "Lax", "path": "/"},
        ),
        (
            REFRESH_COOKIE,
            refresh,
            {
                "max_age": REFRESH_TTL_DAYS * 86400,
                "httponly": True,
                "samesite": "Lax",
                "path": "/api/v1/auth",
            },
        ),
    ]


def clear_auth_cookies():
    return [
        (ACCESS_COOKIE, "", {"max_age": 0, "path": "/"}),
        (REFRESH_COOKIE, "", {"max_age": 0, "path": "/api/v1/auth"}),
    ]
