"""Mission (delivery run) lifecycle — exact port (LK-MSN-01..05).

Reference: main/app.py lines 2577-2802, 2611-2713.
"""

from odoo import fields

from .audit import audit_row
from .notification import notify
from .wallet import credit_livreur_delivery, credit_supplier_sale

MISSION_TRANSITIONS = {
    "ACCEPTED": {"STARTED", "CANCELLED"},
    "CREATED": {"ACCEPTED", "STARTED", "CANCELLED"},
    "STARTED": {"PICKUP_INITIATED", "PICKED_UP", "CANCELLED"},
    "PICKUP_INITIATED": {"PICKED_UP", "CANCELLED"},
    "PICKED_UP": {"IN_TRANSIT", "DELIVERED", "CANCELLED"},
    "IN_TRANSIT": {"DELIVERED", "CANCELLED"},
    "DELIVERED": set(),
    "CANCELLED": set(),
}

MISSION_STATUS_LABELS = {
    "CREATED": "Creee",
    "ACCEPTED": "Acceptee — a demarrer",
    "STARTED": "Course demarree — vers le fournisseur",
    "PICKUP_INITIATED": "Recuperation initialisee — en attente colis recu",
    "PICKED_UP": "Colis recu",
    "IN_TRANSIT": "En route vers le client",
    "DELIVERED": "Livree",
    "CANCELLED": "Annulee",
}

MISSION_NEXT_ACTION = {
    "ACCEPTED": {"action": "start", "label": "Demarrer la course", "confirm": "Etes-vous sur de demarrer la course ?"},
    "CREATED": {"action": "start", "label": "Demarrer la course", "confirm": "Etes-vous sur de demarrer la course ?"},
    "STARTED": {"action": "init_pickup", "label": "Initialiser la recuperation du colis", "confirm": "Initialiser la recuperation du colis chez le fournisseur ?"},
    "PICKUP_INITIATED": {"action": "confirm_received", "label": "Colis recu", "confirm": "Confirmer que le colis a bien ete recu ?"},
    "PICKED_UP": {"action": "en_route", "label": "En route vers le client", "confirm": "Etes-vous sur de partir vers le client ?"},
    "IN_TRANSIT": {"action": "deliver", "label": "Confirmer la livraison (OTP)", "confirm": "Confirmer la livraison au client ?"},
}


def apply_mission_status(env, run, new_status, actor, otp=None):
    """LK-MSN-02..05 — transition checks + order sync + notifications + audit.

    actor: dict-like {"id": partner_id, "role": role} for the audit row, or
    a likdelivery.user. Raises ValueError with the reference French messages.
    """
    current = run.state or "CREATED"
    if new_status == current:
        return run
    allowed = MISSION_TRANSITIONS.get(current, set())
    if new_status not in allowed:
        raise ValueError(
            f"Transition invalide: {current} → {new_status}. "
            f"Etapes: Acceptee → Demarrer → Recuperer → En route client → Livrer"
        )

    order = run.order_id or None

    if new_status == "DELIVERED":
        # COD: payment must be confirmed by livreur before finishing the run
        if order and order.payment_method == "cash_on_delivery" and order.payment_status != "paid":
            raise ValueError(
                "Paiement a la livraison non confirme. "
                "Confirmez d'abord que le client a paye, puis saisissez l'OTP."
            )
        # Require OTP shown to client (on order detail / delivery run)
        expected = (run.otp_code or "").upper()
        if not otp or str(otp).strip().upper() != expected:
            raise ValueError("OTP client requis pour confirmer la livraison")

    run.state = new_status
    now = fields.Datetime.now()

    if new_status == "STARTED":
        if order:
            order.state = "PICKUP_IN_PROGRESS"
        notify_msg = "Le livreur a demarre la course et se dirige vers le point de retrait."
    elif new_status == "PICKUP_INITIATED":
        if order:
            order.state = "PICKUP_IN_PROGRESS"
        notify_msg = (
            "Recuperation du colis initialisee chez le fournisseur. "
            "Confirmez 'Colis recu' (client ou livreur) quand le colis est en main."
        )
        if order:
            notify(
                env,
                partner=order.supplier_id,
                title="Recuperation en cours",
                body=f"Commande {order.code}: recuperation initialisee.",
                link="#supplier",
            )
    elif new_status == "PICKED_UP":
        run.pickup_time = now
        if order:
            order.state = "OUT_FOR_DELIVERY" if order.mode == "delivery" else "PICKUP_IN_PROGRESS"
        notify_msg = "Colis recu confirme."
    elif new_status == "IN_TRANSIT":
        if order:
            order.state = "OUT_FOR_DELIVERY"
        notify_msg = "Le livreur est en route vers vous."
    elif new_status == "DELIVERED":
        run.delivery_time = now
        if order:
            order.state = "DELIVERED"
            credit_supplier_sale(env, order)
        if run.livreur_id:
            credit_livreur_delivery(run.livreur_id, run.price)
        notify_msg = "Votre commande a ete livree."
    elif new_status == "CANCELLED":
        notify_msg = "La course a ete annulee par le livreur."
    else:
        notify_msg = f"Statut livraison: {new_status}"

    if order:
        notify(
            env,
            partner=order.client_id or None,
            guest_phone=order.guest_phone if not order.client_id else None,
            title="Suivi livraison",
            body=f"Commande {order.code}: {notify_msg}",
            link=f"#order?id={order.id}",
        )
    _audit_run_status(env, actor, run, new_status)
    return run


def _audit_run_status(env, actor, run, new_status):
    actor_id = None
    actor_role = None
    if hasattr(actor, "partner_id"):  # likdelivery.user
        actor_id = actor.partner_id.id
        actor_role = actor.lik_role
    elif isinstance(actor, dict):
        actor_id = actor.get("id")
        actor_role = actor.get("role")
    env["likdelivery.audit.log"].sudo().create(
        {
            "actor_id": actor_id,
            "actor_role": actor_role,
            "action": "UPDATE_RUN_STATUS",
            "target_type": "DeliveryRun",
            "target_id": run.id,
            "details": '{"new_status": "%s"}' % new_status,
        }
    )


def mission_dict(env, run):
    """LK-MSN-05 — driver-facing mission payload (_mission_dict port)."""
    order_code = None
    supplier_name = None
    supplier_phone = None
    client_phone = None
    contact_phone = None
    client_name = None
    client_first_name = None
    client_last_name = None
    order_status = None
    order_mode = None
    delivery_address = None
    payment_method = None
    payment_status = None
    order_total = None
    order = run.order_id or None
    if order:
        order_code = order.code
        order_status = order.state
        order_mode = order.mode
        delivery_address = order.delivery_address or run.dropoff_address
        payment_method = order.payment_method
        payment_status = order.payment_status
        order_total = order.total
        client = order.client_id or None
        if client:
            client_first_name = client.lik_first_name or ""
            client_last_name = client.lik_last_name or ""
            client_name = f"{client_first_name} {client_last_name}".strip() or client.phone
        else:
            client_name = f"Invite ({order.guest_phone})" if order.guest_phone else "Destinataire"
        # Prefer phone entered at checkout (destinataire) for the call button
        contact_phone = (order.guest_phone or (client.phone if client else None) or "").strip() or None
        client_phone = contact_phone
        supplier = order.supplier_id
        if supplier:
            supplier_name = (
                supplier.lik_company_name
                or f"{supplier.lik_first_name or ''} {supplier.lik_last_name or ''}".strip()
            )
            supplier_phone = supplier.phone
    needs_cod_payment = (
        payment_method == "cash_on_delivery"
        and payment_status != "paid"
        and run.state in ("IN_TRANSIT", "PICKED_UP")
    )
    payment_ok_for_deliver = (
        payment_status == "paid" or payment_method not in ("cash_on_delivery",)
    )
    next_action = MISSION_NEXT_ACTION.get(run.state)
    if needs_cod_payment:
        next_action = {
            "action": "confirm_cod_payment",
            "label": "Confirmer paiement recu du client",
            "confirm": "Confirmer que le client a paye le montant a la livraison ?",
        }
    elif run.state == "IN_TRANSIT" and payment_ok_for_deliver:
        next_action = MISSION_NEXT_ACTION.get("IN_TRANSIT")
    return {
        "id": run.id,
        "status": run.state,
        "status_label": MISSION_STATUS_LABELS.get(run.state, run.state),
        "order_id": order.id if order else None,
        "order_code": order_code,
        "order_status": order_status,
        "order_mode": order_mode,
        "order_total": order_total,
        "payment_method": payment_method,
        "payment_status": payment_status,
        "needs_cod_payment": needs_cod_payment,
        "payment_ok_for_deliver": payment_ok_for_deliver,
        "supplier_name": supplier_name,
        "supplier_phone": supplier_phone,
        "client_name": client_name,
        "client_first_name": client_first_name,
        "client_last_name": client_last_name,
        "client_phone": client_phone,
        "contact_phone": contact_phone,
        "recipient_name": client_name,
        "recipient_phone": contact_phone,
        "delivery_address": delivery_address or run.dropoff_address,
        "pickup_address": run.pickup_address,
        "dropoff_address": run.dropoff_address or delivery_address,
        "pickup_lat": run.pickup_lat,
        "pickup_lon": run.pickup_lon,
        "dropoff_lat": run.dropoff_lat,
        "dropoff_lon": run.dropoff_lon,
        "distance_km": run.distance_km,
        "price": run.price,
        "is_fragile": run.is_fragile,
        "otp_code": run.otp_code or None,
        "qr_token": run.qr_token or None,
        "pickup_time": run.pickup_time.isoformat() if run.pickup_time else None,
        "delivery_time": run.delivery_time.isoformat() if run.delivery_time else None,
        "next_action": next_action,
        "can_start": run.state in ("ACCEPTED", "CREATED"),
        "can_init_pickup": run.state == "STARTED",
        "can_confirm_received": run.state in ("STARTED", "PICKUP_INITIATED"),
        "can_pickup": run.state in ("STARTED", "PICKUP_INITIATED"),
        "can_en_route": run.state == "PICKED_UP",
        "can_confirm_cod_payment": needs_cod_payment,
        "can_deliver": run.state in ("PICKED_UP", "IN_TRANSIT") and payment_ok_for_deliver,
    }


def confirm_cod_payment(env, lik_user, run):
    """LK-MSN-03 — driver confirms cash received before OTP delivery."""
    order = run.order_id or None
    if not order:
        raise ValueError("Commande introuvable")
    if order.payment_method != "cash_on_delivery":
        raise ValueError("Cette commande n'est pas en paiement a la livraison")
    if order.payment_status == "paid":
        result = mission_dict(env, run)
        result["message"] = "Paiement deja confirme."
        return result
    if run.state not in ("IN_TRANSIT", "PICKED_UP"):
        raise ValueError(
            "Confirmez le paiement seulement a l'arrivee chez le client (course en route / colis en main)."
        )
    order.payment_status = "paid"
    notify(
        env,
        partner=order.client_id or None,
        guest_phone=order.guest_phone if not order.client_id else None,
        title="Paiement a la livraison",
        body=(
            f"Paiement de {order.total:.0f} XOF confirme pour {order.code}. "
            f"Le livreur peut terminer avec l'OTP."
        ),
        link=f"#order?id={order.id}",
    )
    audit_row(
        env, lik_user, "CONFIRM_COD_PAYMENT", "Order", order.id,
        {"amount": order.total, "run_id": run.id},
    )
    result = mission_dict(env, run)
    result["message"] = (
        f"Paiement COD confirme ({order.total:.0f} XOF). "
        "Vous pouvez maintenant saisir l'OTP pour terminer la course."
    )
    return result
