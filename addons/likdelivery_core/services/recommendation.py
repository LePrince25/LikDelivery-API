"""Recommendation & listing service — rating-based driver ranking (LK-REC-01).

No ML: the reference ranks by average_rating DESC, total_deliveries DESC.
Reference: main/app.py lines 2539-2575.
"""

from datetime import datetime

from .pricing import is_night_time

RECOMMENDED_LIMIT = 10
NIGHT_MIN_RATING = 4.0
HIGH_VALUE_MIN_RATING = 4.5


def _livreur_domain():
    return [("lik_role", "=", "livreur"), ("active", "=", True)]


def list_livreurs(env, available_now=False, min_rating=None):
    """LK-CAT-03 — public driver list.

    available_now quirk (LK-SEC-03 ported): joined against opening hours
    using UTC time, not the business timezone.
    """
    domain = _livreur_domain()
    if min_rating is not None:
        domain.append(("lik_average_rating", ">=", float(min_rating)))
    partners = env["res.partner"].sudo().search(domain)
    if available_now:
        now = datetime.utcnow()
        today = str(now.weekday())
        current = now.hour + now.minute / 60.0 + now.second / 3600.0
        hours = env["likdelivery.opening.hour"].sudo().search(
            [
                ("partner_id", "in", partners.ids),
                ("day_of_week", "=", today),
                ("open_time", "<=", current),
                ("close_time", ">=", current),
            ]
        )
        partners = partners.filtered(lambda p: p.id in set(hours.mapped("partner_id").ids))
    return partners.sorted(
        key=lambda p: (p.lik_average_rating, p.lik_total_deliveries), reverse=True
    )


def recommended_livreurs(env, night=False, high_value=False):
    """LK-REC-01 — top rated drivers, stricter at night / for high value."""
    domain = _livreur_domain()
    if night or is_night_time():
        domain.append(("lik_average_rating", ">=", NIGHT_MIN_RATING))
    if high_value:
        domain.append(("lik_average_rating", ">=", HIGH_VALUE_MIN_RATING))
    partners = env["res.partner"].sudo().search(domain)
    ordered = partners.sorted(
        key=lambda p: (p.lik_average_rating, p.lik_total_deliveries), reverse=True
    )
    return ordered[:RECOMMENDED_LIMIT]
