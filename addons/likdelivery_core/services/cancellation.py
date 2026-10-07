"""Cancellation service (E22) — 80/20 penalty rule (LK-CAN-01..04).

Exact port of main/app.py lines 3121-3161, quirks included.
"""

from .audit import audit_row
from .notification import notify
from .order_lifecycle import OrderForbidden, OrderNotFound
from ..models.lik_utils import generate_code

DEFAULT_PENALTY_PERCENT = 80.0
BLOCKED_STATES = ("DELIVERED", "CANCELLED", "FAILED")


def cancel_order(env, lik_user, order):
    """Cancel an order with penalty/refund logic.

    Quirk ported (LK-SEC-02): ownership is only checked when the caller is
    a client — any other authenticated role (and guests) may cancel.
    """
    if not order.exists():
        raise OrderNotFound("Commande inconnue")
    if lik_user and lik_user.lik_role == "client" and order.client_id.id != lik_user.partner_id.id:
        raise OrderForbidden("Non autorise")
    if order.state in BLOCKED_STATES:
        raise ValueError("Commande non annulable")

    rule = env["likdelivery.cancellation.rule"].sudo().search(
        [("active", "=", True)], order="id", limit=1
    )
    penalty_pct = rule.penalty_percent if rule else DEFAULT_PENALTY_PERCENT
    penalty = round(order.total * penalty_pct / 100, 0)
    refund = order.total - penalty

    order.state = "CANCELLED"

    if order.payment_status == "paid":
        # Refund 20% to customer
        env["likdelivery.payment.transaction"].sudo().create(
            {
                "target_type": "order",
                "order_id": order.id,
                "amount": refund,
                "provider": "refund",
                "phone": order.guest_phone or (order.client_id.phone if order.client_id else None),
                "state": "success",
                "provider_ref": generate_code("REF-", 12),
            }
        )
        payment_action = (
            f"; remboursement de {refund:.0f} XOF effectue ({100 - penalty_pct:.0f}%)"
        )
    else:
        # Debt is text-only (LK-SEC-06) — no accounting record
        payment_action = f"; client redevable de {penalty:.0f} XOF ({penalty_pct:.0f}%)"

    notify(
        env,
        partner=order.client_id or None,
        guest_phone=order.guest_phone if not order.client_id else None,
        title="Commande annulee",
        body=f"Votre commande {order.code} a ete annulee. {payment_action}",
        link=f"#/order?id={order.id}",
    )
    audit_row(
        env, lik_user or {"role": "guest"}, "CANCEL_ORDER", "Order", order.id,
        {"penalty": penalty, "refund": refund, "penalty_percent": penalty_pct},
    )
    return {
        "message": "Commande annulee",
        "penalty": penalty,
        "refund": refund,
        "penalty_percent": penalty_pct,
    }
