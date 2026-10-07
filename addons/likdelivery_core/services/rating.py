"""Rating service (E25) — client 1–5 stars (LK-RAT-01/02).

Exact port of main/app.py lines 3233-3299.
"""

from .audit import audit_row
from .order_lifecycle import OrderForbidden


def rate(env, lik_user, data):
    """Rate an order (must be own + DELIVERED) and/or a run; recomputes the
    driver's average over ALL rated runs (round 2)."""
    try:
        stars = int(data.get("stars", 5))
    except (TypeError, ValueError):
        stars = 5
    if stars < 1 or stars > 5:
        raise ValueError("La note doit etre entre 1 et 5")
    comment = data.get("comment")
    run = None
    order = None

    if data.get("order_id"):
        order = env["likdelivery.order"].sudo().browse(data["order_id"])
        if not order.exists() or order.client_id.id != lik_user.partner_id.id:
            raise ValueError("Commande invalide")
        if order.state != "DELIVERED":
            raise ValueError("Vous ne pouvez noter qu'apres la livraison")
        order.rating = stars
        order.rating_comment = comment
        # Also rate the linked delivery run so the livreur score is updated
        run = env["likdelivery.delivery.run"].sudo().search(
            [("order_id", "=", order.id), ("state", "=", "DELIVERED")],
            order="id desc",
            limit=1,
        )

    if data.get("run_id"):
        run = env["likdelivery.delivery.run"].sudo().browse(data["run_id"])
        if not run.exists():
            raise ValueError("Course invalide")
        if run.order_id:
            order = run.order_id
            if order and order.client_id.id != lik_user.partner_id.id:
                raise OrderForbidden("Course non autorisee")

    if run:
        run.rating = stars
        run.rating_comment = comment
        liv = run.livreur_id
        if liv:
            rated = env["likdelivery.delivery.run"].sudo().search(
                [("livreur_id", "=", liv.id), ("rating", "!=", False)]
            )
            ratings = [r.rating for r in rated if r.rating is not None]
            if ratings:
                liv.lik_average_rating = round(sum(ratings) / len(ratings), 2)

    if not order and not run:
        raise ValueError("order_id ou run_id requis")

    audit_row(
        env, lik_user, "RATE",
        "Order" if order else "DeliveryRun",
        order.id if order else run.id,
        {"stars": stars},
    )
    out = {"message": "Note enregistree", "stars": stars}
    if run and run.livreur_id:
        out["livreur_average_rating"] = run.livreur_id.lik_average_rating
        out["livreur_id"] = run.livreur_id.id
    return out
