"""Availability service — opening hours engine (LK-HRS-01).

Exact port of the reference is_open_now / _time_in_open_range /
supplier_availability, including the French reason strings verbatim.
Times are stored as float hours on likdelivery.opening.hour (6.5 = 06:30);
comparisons preserve the reference datetime.time semantics.
Reference: main/app.py lines 92-161.
"""

from .pricing import now_business

DAY_NAMES_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]


def float_to_hhmm(value):
    """6.5 → '06:30' (serializer helper, matches strftime('%H:%M') output)."""
    hours = int(value)
    minutes = round((value - hours) * 60)
    if minutes == 60:
        hours += 1
        minutes = 0
    return "%02d:%02d" % (hours % 24, minutes)


def _time_in_open_range(open_t, close_t, current_t):
    """True if current_t (float hour) is within [open_t, close_t].
    open == close → explicitly closed that day. Overnight windows supported."""
    if open_t is None or close_t is None:
        return True
    if open_t == close_t:
        return False
    if open_t < close_t:
        return open_t <= current_t <= close_t
    # overnight window e.g. 22.0–6.0
    return current_t >= open_t or current_t <= close_t


def is_open_now(partner, at=None):
    """LK-HRS-01 — open check in business timezone.

    day_of_week ISO Monday=0. No hours configured for the day → open
    (no restriction).
    """
    now = at or now_business()
    day = now.weekday()
    current = now.hour + now.minute / 60.0 + now.second / 3600.0
    rows = partner.env["likdelivery.opening.hour"].sudo().search(
        [("partner_id", "=", partner.id), ("day_of_week", "=", str(day))]
    )
    if not rows:
        return True
    return any(
        _time_in_open_range(h.open_time, h.close_time, current) for h in rows
    )


def opening_hours_payload(partner):
    """Hours list + open_now + server clock (public endpoint E10)."""
    hours = partner.env["likdelivery.opening.hour"].sudo().search(
        [("partner_id", "=", partner.id)], order="day_of_week, open_time"
    )
    now = now_business()
    return {
        "hours": [
            {
                "day_of_week": int(h.day_of_week),
                "day_name": DAY_NAMES_FR[int(h.day_of_week)],
                "open_time": float_to_hhmm(h.open_time),
                "close_time": float_to_hhmm(h.close_time),
                "closed_day": h.open_time == h.close_time,
            }
            for h in hours
        ],
        "open_now": is_open_now(partner),
        "server_local_time": now.strftime("%Y-%m-%d %H:%M"),
        "server_weekday": DAY_NAMES_FR[now.weekday()],
    }


def supplier_availability(supplier):
    """LK-CHK-02 — (ok, reason) for order placement checks.

    French reason strings ported verbatim from the reference.
    """
    if not supplier or not supplier.exists():
        return False, "Fournisseur introuvable"
    if supplier.lik_role != "fournisseur":
        return False, "Compte non fournisseur"
    display = supplier.lik_company_name or supplier.phone
    if not supplier.active:
        return False, f"{display} : compte desactive"
    if not supplier.lik_validated_by_admin:
        return False, (
            f"{display} : non valide par l'admin "
            f"(apres KYC, une re-validation admin est requise)"
        )
    if not is_open_now(supplier):
        now = now_business()
        day = now.weekday()
        rows = supplier.env["likdelivery.opening.hour"].sudo().search(
            [("partner_id", "=", supplier.id), ("day_of_week", "=", str(day))]
        )
        if rows:
            windows = ", ".join(
                f"{float_to_hhmm(h.open_time)}-{float_to_hhmm(h.close_time)}"
                for h in rows
            )
            return False, (
                f"{display} : ferme actuellement "
                f"({DAY_NAMES_FR[day]} {now.strftime('%H:%M')}, horaires: {windows})"
            )
        return False, f"{display} : ferme actuellement"
    return True, None


def replace_opening_hours(env, lik_user, items):
    """LK-HRS-01 — POST replaces ALL hours of the user (E35/E58).

    items: list of {day_of_week 0..6, open_time "HH:MM", close_time "HH:MM"}.
    Raises ValueError('Format invalide: ...') on bad input.
    """
    partner = lik_user.partner_id
    Hour = env["likdelivery.opening.hour"].sudo()
    Hour.search([("partner_id", "=", partner.id)]).unlink()
    try:
        for item in items:
            day = int(item["day_of_week"])
            if day < 0 or day > 6:
                raise ValueError("day_of_week doit etre 0(Lundi)..6(Dimanche)")
            Hour.create(
                {
                    "partner_id": partner.id,
                    "day_of_week": str(day),
                    "open_time": _hhmm_to_float(item["open_time"]),
                    "close_time": _hhmm_to_float(item["close_time"]),
                }
            )
    except Exception as err:
        raise ValueError(f"Format invalide: {err}")
    from .audit import audit_row

    audit_row(env, lik_user, "UPDATE_OPENING_HOURS", "User", lik_user.id)
    return {
        "message": "Horaires mis a jour",
        "open_now": is_open_now(partner),
        "convention": "ISO Monday=0 (Lundi) .. Sunday=6 (Dimanche)",
    }


def _hhmm_to_float(value):
    hours, minutes = str(value).split(":")
    return int(hours) + int(minutes) / 60.0


def self_hours_payload(env, lik_user):
    """GET shape for own hours (E35/E58): list + open status + today rows."""
    partner = lik_user.partner_id
    hours = env["likdelivery.opening.hour"].sudo().search(
        [("partner_id", "=", partner.id)], order="day_of_week, open_time"
    )
    result = [
        {
            "id": h.id,
            "day_of_week": int(h.day_of_week),
            "day_name": DAY_NAMES_FR[int(h.day_of_week)],
            "open_time": float_to_hhmm(h.open_time),
            "close_time": float_to_hhmm(h.close_time),
            "closed_day": h.open_time == h.close_time,
        }
        for h in hours
    ]
    open_now = is_open_now(partner)
    now = now_business()
    today = now.weekday()
    return {
        "hours": result,
        "convention": "ISO Monday=0 .. Sunday=6",
        "open_now": open_now,
        "status_label": "OUVERT" if open_now else "FERME",
        "server_local_time": now.strftime("%Y-%m-%d %H:%M"),
        "server_weekday": DAY_NAMES_FR[now.weekday()],
        "today_day_of_week": today,
        "today_hours": [h for h in result if h["day_of_week"] == today],
    }
