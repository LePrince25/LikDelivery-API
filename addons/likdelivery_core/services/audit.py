"""Audit helper for services (LK-AUD-01) — no request dependency."""


def audit_row(env, actor, action, target_type=None, target_id=None, details=None):
    """actor: likdelivery.user, res.partner, or dict {id, role}."""
    import json as _json

    actor_id = None
    actor_role = None
    if isinstance(actor, dict):
        actor_id = actor.get("id")
        actor_role = actor.get("role")
    elif actor is not None and getattr(actor, "id", None):
        if hasattr(actor, "partner_id") and hasattr(actor, "lik_role"):  # lik user
            actor_id = actor.partner_id.id
            actor_role = actor.lik_role
        elif hasattr(actor, "lik_role"):  # partner
            actor_id = actor.id
            actor_role = actor.lik_role
    env["likdelivery.audit.log"].sudo().create(
        {
            "actor_id": actor_id,
            "actor_role": actor_role,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "details": _json.dumps(details, default=str) if details else None,
        }
    )
