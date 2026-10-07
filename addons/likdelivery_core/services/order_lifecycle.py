"""Order lifecycle service — serializer, scoping, status updates, pickup
actions (LK-ORD-01..05). Exact port of the reference.

Reference: main/app.py lines 321-427 (order_to_dict, can_view_order),
1603-1620 (list scoping), 1721-1744 (supplier status), 2942-3030
(pickup-action).
"""

from .mission_lifecycle import apply_mission_status, mission_dict
from .notification import notify
from .wallet import credit_supplier_sale

ALLOWED_STATUSES = [
    "CREATED", "PREPARING", "PICKUP_IN_PROGRESS", "OUT_FOR_DELIVERY",
    "DELIVERED", "CANCELLED", "FAILED",
]
BLOCKED_STATES = ("CANCELLED", "DELIVERED", "FAILED")


class OrderNotFound(ValueError):
    pass


class OrderForbidden(PermissionError):
    pass


def payment_ready(order):
    """LK-ASN-04 — paid or cash method."""
    return order.payment_status == "paid" or order.payment_method in (
        "cash_on_delivery",
        "pay_at_pickup",
    )


def active_run_for_order(order):
    """Non-CANCELLED run, most recent first."""
    runs = order.run_ids.filtered(lambda r: r.state != "CANCELLED")
    return runs.sorted(key=lambda r: r.create_date, reverse=True)[:1]


def order_to_dict(env, order, detailed=False):
    """LK-ORD-03 — reference order_to_dict (computed handover flags included)."""
    supplier = order.supplier_id
    client = order.client_id or None
    if client:
        client_name = (
            f"{client.lik_first_name or ''} {client.lik_last_name or ''}".strip()
            or client.phone
        )
    elif order.guest_phone:
        client_name = f"Invite ({order.guest_phone})"
    else:
        client_name = None
    ready = payment_ready(order)
    shop_livreur_count = env["likdelivery.shop.driver"].sudo().search_count(
        [("supplier_id", "=", order.supplier_id.id), ("is_active", "=", True)]
    )
    has_shop_livreurs = shop_livreur_count > 0
    open_for_platform = bool(order.open_for_platform_claim)
    runs = order.run_ids
    active_run = active_run_for_order(order)
    assigned = bool(active_run and active_run.livreur_id)

    can_assign_shop_livreur = (
        ready
        and order.mode == "delivery"
        and has_shop_livreurs
        and not assigned
        and order.state not in BLOCKED_STATES
    )
    can_init_handover = ready and order.state not in BLOCKED_STATES + (
        "PICKUP_IN_PROGRESS",
    ) and (
        order.mode == "pickup"
        or (order.mode == "delivery" and not has_shop_livreurs and not assigned)
        or (order.mode == "delivery" and assigned)
    )
    handover_initialized = order.state in ("PICKUP_IN_PROGRESS", "OUT_FOR_DELIVERY") or open_for_platform
    handover_for = None
    if order.mode == "pickup":
        handover_for = "client"
    elif assigned:
        handover_for = "livreur"
    elif has_shop_livreurs:
        handover_for = "livreur_boutique"
    elif open_for_platform or handover_initialized:
        handover_for = "plateforme"
    elif order.mode == "delivery":
        handover_for = "a_definir"

    soc = order.preferred_societe_id
    return {
        "id": order.id,
        "code": order.code,
        "status": order.state,
        "mode": order.mode,
        "supplier_name": supplier.lik_company_name or "",
        "supplier_phone": supplier.phone or "",
        "supplier_id": supplier.id,
        "client_id": order.client_id.id or None,
        # Prefer phone entered at checkout for delivery contact
        "client_phone": order.guest_phone or (client.phone if client else ""),
        "contact_phone": order.guest_phone or (client.phone if client else ""),
        "client_name": client_name,
        "delivery_address": order.delivery_address,
        "delivery_lat": order.delivery_lat,
        "delivery_lon": order.delivery_lon,
        "product_total": order.product_total,
        "delivery_fee": order.delivery_fee,
        "total": order.total,
        "payment_method": order.payment_method,
        "payment_status": order.payment_status,
        "payment_ready": ready,
        "has_shop_livreurs": has_shop_livreurs,
        "shop_livreur_count": shop_livreur_count,
        "open_for_platform_claim": open_for_platform,
        "can_init_handover": can_init_handover,
        "can_assign_shop_livreur": can_assign_shop_livreur,
        "handover_initialized": handover_initialized,
        "handover_for": handover_for,
        "preferred_societe_id": soc.id or None,
        "preferred_societe_name": (soc.lik_company_name or soc.phone) if soc else None,
        "is_fragile": order.is_fragile,
        "created_at": order.create_date.isoformat() if order.create_date else None,
        "updated_at": order.write_date.isoformat() if order.write_date else None,
        "rating": order.rating or None,
        "rating_comment": order.rating_comment or None,
        "otp": order.otp_code if detailed else None,
        "lines": [
            {
                "id": line.id,
                "product_id": line.product_id.id,
                "quantity": line.quantity,
                "unit_price": line.unit_price,
                "product_name": line.product_id.name or "",
            }
            for line in order.line_ids
        ],
        "delivery_runs": [
            {
                "id": run.id,
                "status": run.state,
                "livreur_id": run.livreur_id.id or None,
                "livreur_phone": run.livreur_id.phone or "",
                "pickup_lat": run.pickup_lat,
                "pickup_lon": run.pickup_lon,
                "dropoff_lat": run.dropoff_lat,
                "dropoff_lon": run.dropoff_lon,
                "price": run.price,
                "otp_code": run.otp_code if detailed else None,
                "qr_token": run.qr_token if detailed else None,
            }
            for run in runs
        ],
    }


def can_view_order(env, lik_user, order):
    """LK-ORD-03 — reference visibility matrix."""
    role = lik_user.lik_role
    partner_id = lik_user.partner_id.id
    if role == "admin":
        return True
    if role == "client" and order.client_id.id == partner_id:
        return True
    if role == "fournisseur" and order.supplier_id.id == partner_id:
        return True
    if role == "societe" and order.preferred_societe_id.id == partner_id:
        return True
    if role == "livreur":
        return bool(
            env["likdelivery.delivery.run"].sudo().search_count(
                [("order_id", "=", order.id), ("livreur_id", "=", partner_id)]
            )
        )
    return False


def list_orders_for(env, lik_user):
    """LK-ORD-02 — role-scoped list, newest first, non-detailed dicts."""
    Order = env["likdelivery.order"].sudo()
    role = lik_user.lik_role
    partner_id = lik_user.partner_id.id
    if role == "client":
        domain = [("client_id", "=", partner_id)]
    elif role == "fournisseur":
        domain = [("supplier_id", "=", partner_id)]
    elif role == "societe":
        domain = [("preferred_societe_id", "=", partner_id)]
    elif role == "livreur":
        domain = [("run_ids.livreur_id", "=", partner_id)]
    else:  # admin → all orders (no filter)
        domain = []
    orders = Order.search(domain, order="create_date desc")
    return [order_to_dict(env, o) for o in orders]


def update_order_status(env, lik_user, order, new_status):
    """LK-ORD-04 — supplier status endpoint (arbitrary jumps allowed)."""
    if not order.exists():
        raise OrderNotFound("Commande inconnue")
    if (
        lik_user.lik_role == "fournisseur"
        and order.supplier_id.id != lik_user.partner_id.id
    ):
        raise OrderForbidden("Non autorise")
    if new_status not in ALLOWED_STATUSES:
        raise ValueError("Statut invalide")
    order.state = new_status
    if new_status == "DELIVERED":
        credit_supplier_sale(env, order)
    notify(
        env,
        partner=order.client_id or None,
        guest_phone=order.guest_phone if not order.client_id else None,
        title="Commande mise a jour",
        body=f"Votre commande {order.code} est maintenant: {new_status}.",
        link=f"#/order?id={order.id}",
    )
    return {"message": "Statut mis a jour"}


def pickup_action(env, lik_user, order, action):
    """LK-ORD-05 — init_pickup | confirm_received.

    Actor matrix: owning client, owning supplier, assigned livreur, admin.
    """
    action = (action or "").strip().lower()
    if action not in ("init_pickup", "confirm_received"):
        raise ValueError("Action invalide (init_pickup | confirm_received)")
    if not order.exists():
        raise OrderNotFound("Commande inconnue")

    role = lik_user.lik_role
    partner_id = lik_user.partner_id.id
    is_client = role == "client" and order.client_id.id == partner_id
    is_supplier = role in ("fournisseur", "societe") and order.supplier_id.id == partner_id
    run = active_run_for_order(order)
    is_livreur = bool(
        run and run.livreur_id and role == "livreur" and run.livreur_id.id == partner_id
    )
    if role != "admin" and not (is_client or is_supplier or is_livreur):
        raise OrderForbidden("Non autorise")

    # Self-pickup (no livreur): manage order status directly
    if order.mode == "pickup" and not run:
        if action == "init_pickup":
            if order.state in BLOCKED_STATES:
                raise ValueError(f"Commande non disponible ({order.state})")
            order.state = "PICKUP_IN_PROGRESS"
            notify(
                env,
                partner=order.supplier_id,
                title="Retrait client",
                body=f"Client initialise le retrait de {order.code}.",
                link="#supplier",
            )
            notify(
                env,
                partner=order.client_id or None,
                guest_phone=order.guest_phone if not order.client_id else None,
                title="Retrait initialise",
                body=(
                    f"Recuperation de {order.code} initialisee. "
                    f"Cliquez 'Colis recu' une fois le colis en main."
                ),
                link=f"#order?id={order.id}",
            )
            return {
                "message": "Recuperation initialisee. Cliquez Colis recu quand c'est fait.",
                "order": order_to_dict(env, order, detailed=True),
                "_audit": "INIT_PICKUP",
            }
        # confirm_received — reference quirk ported: the status precondition
        # is a no-op, any status is accepted.
        order.state = "DELIVERED"
        credit_supplier_sale(env, order)
        notify(
            env,
            partner=order.supplier_id,
            title="Colis retire",
            body=f"Commande {order.code}: colis recu par le client.",
            link="#supplier",
        )
        return {
            "message": "Colis recu — retrait termine.",
            "order": order_to_dict(env, order, detailed=True),
            "_audit": "CONFIRM_PICKUP_RECEIVED",
        }

    # Delivery with run: client or livreur can confirm steps
    if not run:
        raise ValueError("Aucune course assignee pour cette commande")
    target = "PICKUP_INITIATED" if action == "init_pickup" else "PICKED_UP"
    apply_mission_status(env, run, target, lik_user)
    result = mission_dict(env, run)
    result["message"] = (
        "Recuperation initialisee. En attente de confirmation 'Colis recu'."
        if action == "init_pickup"
        else "Colis recu confirme."
    )
    return result
