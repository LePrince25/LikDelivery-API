"""Payment service (E26–E29) — simulated PSP (LK-PAY-01..03).

Exact port of main/app.py lines 3165-3229. The simulator stays behind this
interface so real Tmoney/Flooz/Ecobank adapters can replace it (D8).
"""

from .audit import audit_row
from .order_lifecycle import OrderNotFound
from ..models.lik_utils import generate_code


def initiate(env, lik_user, data):
    """Create a pending transaction for an order or courier request."""
    target_type = data.get("target_type")
    target_id = data.get("target_id")
    obj = None
    if target_type == "order":
        obj = env["likdelivery.order"].sudo().browse(target_id)
    elif target_type == "courier":
        obj = env["likdelivery.courier.request"].sudo().browse(target_id)
    if obj is None or not obj.exists():
        raise OrderNotFound("Objet invalide")
    amount = obj.total if target_type == "order" else obj.price
    tx = env["likdelivery.payment.transaction"].sudo().create(
        {
            "target_type": target_type,
            "order_id": obj.id if target_type == "order" else None,
            "courier_request_id": obj.id if target_type == "courier" else None,
            "amount": amount,
            "provider": data.get("provider", "tmoney"),
            "phone": data.get("phone", ""),
            "state": "pending",
        }
    )
    audit_row(env, lik_user or {"role": "guest"}, "PAYMENT_INITIATE",
              "PaymentTransaction", tx.id)
    return {
        "transaction_id": tx.id,
        "reference": tx.reference,
        "amount": tx.amount,
        "status": tx.state,
    }


def status(env, reference):
    tx = env["likdelivery.payment.transaction"].sudo().search(
        [("reference", "=", reference)], limit=1
    )
    if not tx:
        raise OrderNotFound("Transaction inconnue")
    return {
        "reference": tx.reference,
        "status": tx.state,
        "amount": tx.amount,
        "provider": tx.provider,
        "updated_at": tx.write_date.isoformat(),
    }


def confirm(env, lik_user, reference, data):
    """Simulated PSP webhook (LK-SEC-04 ported: success is client-controlled)."""
    tx = env["likdelivery.payment.transaction"].sudo().search(
        [("reference", "=", reference)], limit=1
    )
    if not tx:
        raise OrderNotFound("Transaction inconnue")
    success = data.get("simulate_success", True)
    if success:
        tx.state = "success"
        tx.provider_ref = generate_code("PROV-", 12)
        if tx.target_type == "order" and tx.order_id:
            tx.order_id.payment_status = "paid"
        elif tx.target_type == "courier" and tx.courier_request_id:
            tx.courier_request_id.payment_status = "paid"
    else:
        tx.state = "failed"
        tx.failure_reason = data.get("reason", "Echec simulate")
    audit_row(
        env, lik_user or {"role": "guest"}, "PAYMENT_CONFIRM",
        "PaymentTransaction", tx.id, {"status": tx.state},
    )
    return {"reference": tx.reference, "status": tx.state}
