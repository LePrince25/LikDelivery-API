"""Profile service (E05) — exact port of the reference /api/profile
(LK-AUT-05..09). Reference: main/app.py lines 269-296, 538-662."""

from . import wallet
from .audit import audit_row
from .serializers import user_to_dict


def livreur_stats(env, partner):
    """Aggregated livreur mission/wallet stats for profile."""
    Run = env["likdelivery.delivery.run"].sudo()
    delivered = Run.search([("livreur_id", "=", partner.id), ("state", "=", "DELIVERED")])
    active = Run.search(
        [
            ("livreur_id", "=", partner.id),
            ("state", "not in", ["DELIVERED", "CANCELLED"]),
        ]
    )
    cancelled = Run.search(
        [("livreur_id", "=", partner.id), ("state", "=", "CANCELLED")]
    )
    return {
        "delivered_count": len(delivered),
        "active_missions": len(active),
        "cancelled_count": len(cancelled),
        "total_earnings": float(sum(delivered.mapped("price")) or 0),
    }


def profile_payload(env, lik_user):
    """GET shape: user dict + livreur stats/wallet (with total_deliveries
    self-heal, LK-AUT-09) or fournisseur wallet."""
    partner = lik_user.partner_id
    out = user_to_dict(lik_user)
    if lik_user.lik_role == "livreur":
        stats = livreur_stats(env, partner)
        # Keep counter aligned with real delivered missions
        if (partner.lik_total_deliveries or 0) < stats["delivered_count"]:
            partner.sudo().lik_total_deliveries = stats["delivered_count"]
            out["total_deliveries"] = partner.lik_total_deliveries or 0
        snap = wallet.snapshot(partner)
        out["balance"] = snap["available"]
        out["wallet"] = snap
        out.update(
            {
                "stats": stats,
                "full_name": (
                    f"{(partner.lik_first_name or '').strip()} "
                    f"{(partner.lik_last_name or '').strip()}".strip()
                    or partner.phone
                ),
            }
        )
    elif lik_user.lik_role == "fournisseur":
        snap = wallet.snapshot(partner)
        out["balance"] = snap["available"]
        out["wallet"] = snap
    return out


FIELD_MAP = {
    "first_name": "lik_first_name",
    "last_name": "lik_last_name",
    "email": "email",
    "address": "street",
    "company_name": "lik_company_name",
    "vehicle_type": "lik_vehicle_type",
    "license_plate": "lik_license_plate",
}


def update_profile(env, lik_user, data):
    """LK-AUT-05/06/08 — PUT. Password validation happens FIRST, before any
    other mutation (reference ordering). Raises ValueError with the exact
    reference French messages."""
    partner = lik_user.partner_id
    audit_details = {}

    new_password = data.get("new_password")
    wants_password_change = new_password is not None and str(new_password).strip() != ""
    if wants_password_change:
        current_password = data.get("current_password") or ""
        confirm = data.get("new_password_confirm")
        if not lik_user.check_password(current_password):
            raise ValueError("Mot de passe actuel incorrect")
        if len(str(new_password)) < 6:
            raise ValueError(
                "Le nouveau mot de passe doit contenir au moins 6 caracteres"
            )
        if confirm is not None and str(confirm) != str(new_password):
            raise ValueError("La confirmation du mot de passe ne correspond pas")
        if lik_user.check_password(str(new_password)):
            raise ValueError("Le nouveau mot de passe doit etre different de l'ancien")

    vals = {}
    for field in FIELD_MAP:
        if field in data:
            val = data[field]
            if field == "company_name" and isinstance(val, str):
                val = val.strip() or None
            vals[FIELD_MAP[field]] = val
    if "phone" in data:
        new_phone = (data.get("phone") or "").strip()
        if not new_phone:
            raise ValueError("Le numero de telephone est requis")
        cleaned = "".join(ch for ch in new_phone if ch.isdigit() or ch == "+")
        if cleaned.count("+") > 1 or (cleaned and "+" in cleaned[1:]):
            raise ValueError("Numero de telephone invalide")
        digits = cleaned.replace("+", "")
        if len(digits) < 8 or len(digits) > 15:
            raise ValueError("Numero de telephone invalide (8 a 15 chiffres)")
        if cleaned != partner.phone:
            taken = env["likdelivery.user"].sudo().search_count(
                [("phone", "=", cleaned), ("id", "!=", lik_user.id)]
            )
            if taken:
                raise ValueError("Ce numero de telephone est deja utilise")
            audit_details["old_phone"] = partner.phone
            audit_details["new_phone"] = cleaned
            vals["phone"] = cleaned
    if "latitude" in data:
        vals["partner_latitude"] = data["latitude"]
    if "longitude" in data:
        vals["partner_longitude"] = data["longitude"]

    if "preferred_societe_id" in data and lik_user.lik_role == "client":
        raw = data.get("preferred_societe_id")
        if raw in ("", None):
            vals["lik_preferred_societe_id"] = None
        else:
            try:
                sid = int(raw)
            except (TypeError, ValueError):
                raise ValueError("Societe de livraison invalide")
            soc = env["res.partner"].sudo().search(
                [
                    ("id", "=", sid),
                    ("lik_role", "=", "societe"),
                    ("active", "=", True),
                    ("lik_validated_by_admin", "=", True),
                ],
                limit=1,
            )
            if not soc:
                raise ValueError("Societe de livraison introuvable ou non validee")
            vals["lik_preferred_societe_id"] = sid
            audit_details["preferred_societe_id"] = sid

    if vals:
        partner.sudo().write(vals)
    if wants_password_change:
        lik_user.set_password(str(new_password))
        audit_details["password_changed"] = True

    audit_row(env, lik_user, "UPDATE_PROFILE", "User", lik_user.id, audit_details or None)
    return profile_payload(env, lik_user)


def validate_account(env, lik_user, target_partner):
    """LK-KYC-02 — admin validates a fournisseur/societe account."""
    if lik_user.lik_role != "admin":
        raise PermissionError("Non autorise")
    target_partner.lik_validated_by_admin = True
    from .notification import notify

    notify(
        env,
        partner=target_partner,
        title="Compte valide",
        body="Votre compte a ete valide par l'administration.",
    )
    audit_row(env, lik_user, "VALIDATE_USER", "User", target_partner.id)
    return {"message": "Utilisateur valide"}
