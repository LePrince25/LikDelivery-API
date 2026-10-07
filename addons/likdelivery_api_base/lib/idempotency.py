from datetime import datetime, timedelta

from odoo.http import request

IDEMPOTENCY_TTL_HOURS = 24
REPLAY_HEADER = ("Idempotent-Replay", "true")


def get_idempotency_key():
    return request.httprequest.headers.get("Idempotency-Key")


def find_replay(endpoint):
    """Return the stored response body/status for this key, or None."""
    key = get_idempotency_key()
    if not key:
        return None
    lik_user = getattr(request, "lik_user", None)
    cutoff = datetime.utcnow() - timedelta(hours=IDEMPOTENCY_TTL_HOURS)
    record = (
        request.env["likdelivery.idempotency.key"]
        .sudo()
        .search(
            [
                ("key", "=", key),
                ("endpoint", "=", endpoint),
                ("lik_user_id", "=", lik_user.id if lik_user else False),
                ("create_date", ">=", cutoff),
            ],
            limit=1,
        )
    )
    if record:
        return record.status, record.response_body
    return None


def store_response(endpoint, status, body):
    key = get_idempotency_key()
    if not key:
        return
    lik_user = getattr(request, "lik_user", None)
    request.env["likdelivery.idempotency.key"].sudo().create(
        {
            "key": key,
            "endpoint": endpoint,
            "lik_user_id": lik_user.id if lik_user else None,
            "status": status,
            "response_body": body,
        }
    )
