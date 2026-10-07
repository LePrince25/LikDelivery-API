import functools
import json
import logging
import time

from odoo.http import Response, request

_logger = logging.getLogger(__name__)


class ApiError(Exception):
    """Stable-code API error, rendered as the error envelope."""

    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


# --- Error catalogue (stable codes, §02-traceability-matrix / api_base) ---
AUTH_INVALID = ("AUTH_INVALID", 401)
AUTH_EXPIRED = ("AUTH_EXPIRED", 401)
FORBIDDEN = ("FORBIDDEN", 403)
NOT_FOUND = ("NOT_FOUND", 404)
BOLA = ("BOLA", 403)
CONFLICT = ("CONFLICT", 409)
VALIDATION = ("VALIDATION", 400)
RATE_LIMITED = ("RATE_LIMITED", 429)
OTP_INVALID = ("OTP_INVALID", 400)
MISSION_TRANSITION_INVALID = ("MISSION_TRANSITION_INVALID", 400)
WALLET_INSUFFICIENT = ("WALLET_INSUFFICIENT", 400)
PAYMENT_FAILED = ("PAYMENT_FAILED", 400)
INTERNAL = ("INTERNAL", 500)


def raise_error(catalog_entry, message):
    code, status = catalog_entry
    raise ApiError(status, code, message)


def success_response(data, status=200, headers=None, cookies=None):
    body = json.dumps({"ok": True, "data": data}, default=str, ensure_ascii=False)
    response = Response(
        body, status=status, content_type="application/json", headers=headers or []
    )
    for name, value, kwargs in cookies or []:
        response.set_cookie(name, value, **kwargs)
    return response


def error_response(error):
    body = json.dumps(
        {"ok": False, "code": error.code, "error": error.message},
        ensure_ascii=False,
    )
    return Response(body, status=error.status, content_type="application/json")


def json_body():
    return request.httprequest.get_json(silent=True) or {}


def require_fields(data, *fields):
    missing = [f for f in fields if data.get(f) in (None, "")]
    if missing:
        raise_error(VALIDATION, "Champs requis manquants: %s" % ", ".join(missing))


def api_endpoint(roles=None, rate=None):
    """Controller decorator: uniform error envelope + optional role auth.

    roles=None → public endpoint. roles=(...) → authenticated lik user whose
    lik_role must be in the list (mirrors Flask @require_role).
    rate=(key_prefix, limit, window_seconds) → per-IP rate limit.
    """

    def wrap(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            try:
                if rate:
                    from .ratelimit import check_rate_limit

                    check_rate_limit(rate[0], rate[1], rate[2])
                lik_user = None
                if roles is not None:
                    from .jwt_auth import authenticate

                    lik_user = authenticate()
                    # roles=() means "any authenticated role"
                    if roles and lik_user.lik_role not in roles:
                        raise_error(FORBIDDEN, "Acces refuse")
                request.lik_user = lik_user
                return fn(*args, **kwargs)
            except ApiError as err:
                return error_response(err)
            except Exception:
                _logger.exception("Unhandled API error in %s", fn.__name__)
                return error_response(ApiError(500, "INTERNAL", "Erreur interne"))

        return inner

    return wrap


def audit(action, target_type=None, target_id=None, details=None, user=None,
          actor_role=None):
    """Write an audit log row (LK-AUD-01). Extracted to a core service in S11."""
    import json as _json

    lik_user = user or getattr(request, "lik_user", None)
    request.env["likdelivery.audit.log"].sudo().create(
        {
            "actor_id": lik_user.partner_id.id if lik_user else None,
            "actor_role": actor_role or (lik_user.lik_role if lik_user else None),
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "ip": request.httprequest.remote_addr,
            "details": _json.dumps(details, default=str) if details else None,
        }
    )


def anti_enumeration_delay():
    """Constant 50 ms delay on auth failures (LK-AUT, anti-enumeration)."""
    time.sleep(0.05)
