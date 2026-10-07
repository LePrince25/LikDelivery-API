"""Assignment service — 3-pool dispatch, claim, handover, COD confirm,
public delivery validation (LK-ASN-01..05, LK-CLM-01/02, LK-MSN-07).

Exact port. Reference: main/app.py lines 1756-1993 (init-handover,
_assign_livreur_to_order), 2294-2380 (assign-livreur), 2383-2513
(available-orders, claim), 2877-2916 (confirm_cod_payment), 3055-3089
(validate-delivery).
"""

import secrets

from odoo import fields

from . import pricing
from .audit import audit_row
from .mission_lifecycle import apply_mission_status, mission_dict
from .notification import notify
from .order_lifecycle import (
    OrderForbidden,
    OrderNotFound,
    active_run_for_order,
    order_to_dict,
    payment_ready,
)
from .wallet import credit_livreur_delivery, credit_supplier_sale

PICKUP_FALLBACK = (6.13, 1.22)  # LK-PRC-05 — supplier coord fallbacks
DROP_FALLBACK = (6.16, 1.21)
BLOCKED_STATES = ("CANCELLED", "DELIVERED", "FAILED")


def shop_livreur_ids(env, supplier_id):
    rows = env["likdelivery.shop.driver"].sudo().search(
        [("supplier_id", "=", supplier_id), ("is_active", "=", True)]
    )
    return set(rows.mapped("livreur_id").ids)


def fleet_livreur_ids(env, societe_id):
    rows = env["likdelivery.fleet.driver"].sudo().search(
        [("societe_id", "=", societe_id), ("is_active", "=", True)]
    )
    return set(rows.mapped("livreur_id").ids)


def assign_livreur_to_order(env, order, livreur, actor):
    """LK-ASN-03 — create/reuse the run and link the driver.

    livreur: res.partner (role livreur). actor: likdelivery.user or dict.
    Raises ValueError with the reference French messages.
    """
    if order.mode != "delivery":
        raise ValueError("Seules les commandes en livraison peuvent etre assignees")
    if order.state in BLOCKED_STATES:
        raise ValueError(f"Commande non disponible (statut: {order.state})")

    existing = active_run_for_order(order)
    if existing and existing.livreur_id:
        if existing.livreur_id.id == livreur.id:
            raise ValueError("Cette commande vous est deja assignee")
        raise ValueError("Un livreur est deja assigne a cette commande")

    supplier = order.supplier_id
    if not supplier:
        raise ValueError("Fournisseur introuvable")

    pickup_lat = supplier.partner_latitude if supplier.partner_latitude is not None else PICKUP_FALLBACK[0]
    pickup_lon = supplier.partner_longitude if supplier.partner_longitude is not None else PICKUP_FALLBACK[1]
    drop_lat = order.delivery_lat if order.delivery_lat is not None else DROP_FALLBACK[0]
    drop_lon = order.delivery_lon if order.delivery_lon is not None else DROP_FALLBACK[1]

    distance = pricing.haversine(pickup_lat, pickup_lon, drop_lat, drop_lon)
    price, _ = pricing.calculate_run_price(distance, is_fragile=bool(order.is_fragile))

    if existing and not existing.livreur_id:
        run = existing
        run.write(
            {
                "livreur_id": livreur.id,
                "state": "ACCEPTED",
                "otp_code": run.otp_code or secrets.token_hex(3).upper(),
                "qr_token": run.qr_token or secrets.token_urlsafe(32),
                "distance_km": round(distance, 2),
                "price": price,
            }
        )
    else:
        run = env["likdelivery.delivery.run"].sudo().create(
            {
                "order_id": order.id,
                "pickup_address": supplier.street or supplier.lik_company_name or "Point de retrait",
                "pickup_lat": pickup_lat,
                "pickup_lon": pickup_lon,
                "dropoff_address": order.delivery_address or "Adresse client",
                "dropoff_lat": drop_lat,
                "dropoff_lon": drop_lon,
                "distance_km": round(distance, 2),
                "price": price,
                "livreur_id": livreur.id,
                "state": "ACCEPTED",
                "otp_code": secrets.token_hex(3).upper(),
                "qr_token": secrets.token_urlsafe(32),
                "is_fragile": bool(order.is_fragile),
            }
        )

    order.state = "OUT_FOR_DELIVERY"
    order.open_for_platform_claim = False

    notify(
        env,
        partner=livreur,
        title="Nouvelle mission",
        body=f"Mission pour la commande {order.code}. OTP: {run.otp_code}.",
        link="#livreur",
    )
    notify(
        env,
        partner=order.client_id or None,
        guest_phone=order.guest_phone if not order.client_id else None,
        title="Livreur assigne",
        body=f"Votre commande {order.code} est en cours de livraison.",
        link=f"#order?id={order.id}",
    )
    audit_row(
        env, actor, "ASSIGN_LIVREUR", "DeliveryRun", run.id,
        {"order_id": order.id, "livreur_id": livreur.id},
    )
    return run


def assign_by_actor(env, lik_user, order, livreur_id):
    """LK-ASN-01/02 — E42: fournisseur (shop pool), societe (fleet), admin (any)."""
    if not order.exists():
        raise OrderNotFound("Commande inconnue")
    role = lik_user.lik_role
    partner_id = lik_user.partner_id.id
    source = "admin"

    if role == "fournisseur":
        if order.supplier_id.id != partner_id:
            raise OrderForbidden("Non autorise")
        if order.preferred_societe_id:
            raise OrderForbidden(
                "Cette commande est reservee a la societe de livraison choisie par le client."
            )
        source = "boutique"
    elif role == "societe":
        if order.preferred_societe_id.id != partner_id:
            raise OrderForbidden("Cette commande ne vous est pas assignee (choix client)")
        source = "societe"

    livreur = env["res.partner"].sudo().search(
        [("id", "=", livreur_id), ("lik_role", "=", "livreur"), ("active", "=", True)],
        limit=1,
    )
    if not livreur:
        raise ValueError("Livreur invalide ou inactif")

    if role == "fournisseur":
        shop_ids = shop_livreur_ids(env, order.supplier_id.id)
        if shop_ids and livreur.id not in shop_ids:
            raise ValueError(
                "Ce livreur n'est pas associe a votre boutique. "
                "Choisissez un livreur de votre boutique, ou retirez les associations pour ouvrir a la plateforme."
            )
    elif role == "societe":
        fleet_ids = fleet_livreur_ids(env, partner_id)
        if not fleet_ids:
            raise ValueError("Aucun livreur dans votre flotte. Ajoutez-en un d'abord.")
        if livreur.id not in fleet_ids:
            raise ValueError("Ce livreur n'appartient pas a votre flotte.")

    run = assign_livreur_to_order(env, order, livreur, lik_user)
    # After assign, also ready package if payment ready
    if payment_ready(order) and order.state in ("CREATED", "PREPARING", "PICKUP_IN_PROGRESS"):
        order.state = "PICKUP_IN_PROGRESS"
        if run.state in ("CREATED", "ACCEPTED", "STARTED"):
            try:
                apply_mission_status(env, run, "PICKUP_INITIATED", lik_user)
            except ValueError:
                pass
    return {
        "delivery_run_id": run.id,
        "otp": run.otp_code,
        "order_id": order.id,
        "order_code": order.code,
        "livreur_id": livreur.id,
        "livreur_name": (
            f"{livreur.lik_first_name or ''} {livreur.lik_last_name or ''}".strip()
            or livreur.phone
        ),
        "status": run.state,
        "message": "Livreur assigne avec succes",
        "source": source,
    }


def init_handover(env, lik_user, order):
    """LK-ASN-04/05 — E39: mark the package ready (client / assigned driver /
    platform pool)."""
    if not order.exists():
        raise OrderNotFound("Commande inconnue")
    role = lik_user.lik_role
    if role in ("fournisseur", "societe") and order.supplier_id.id != lik_user.partner_id.id:
        raise OrderForbidden("Non autorise")
    if order.state in BLOCKED_STATES:
        raise ValueError(f"Commande non disponible (statut: {order.state})")
    if not payment_ready(order):
        raise ValueError(
            "Le paiement des produits n'est pas encore confirme. "
            "Attendez le paiement ou utilisez le mode paiement a la livraison/retrait."
        )

    has_shop_livreurs = bool(shop_livreur_ids(env, order.supplier_id.id))
    run = active_run_for_order(order)

    if order.mode == "delivery" and has_shop_livreurs and not (run and run.livreur_id):
        raise ValueError(
            "Votre boutique a des livreurs associes. Choisissez d'abord un livreur de la boutique pour cette course."
        )

    if order.state == "PICKUP_IN_PROGRESS" and (
        order.mode == "pickup" or (run and run.livreur_id) or order.open_for_platform_claim
    ):
        return {
            "message": "Retrait deja initialise pour cette commande.",
            "order": order_to_dict(env, order, detailed=True),
            "handover_for": (
                "client" if order.mode == "pickup"
                else ("livreur" if run and run.livreur_id else "plateforme")
            ),
        }

    order.state = "PICKUP_IN_PROGRESS"
    handover_for = "client" if order.mode == "pickup" else "livreur"
    livreur = None

    if order.mode == "delivery":
        if run and run.livreur_id:
            livreur = run.livreur_id
            if run.state in ("CREATED", "ACCEPTED", "STARTED"):
                try:
                    apply_mission_status(env, run, "PICKUP_INITIATED", lik_user)
                except ValueError:
                    if run.state != "PICKED_UP":
                        run.state = "PICKUP_INITIATED"
            order.open_for_platform_claim = False
            handover_for = "livreur"
        else:
            # No shop livreur / no assignment → open to platform + admin
            order.open_for_platform_claim = True
            handover_for = "plateforme"
    else:
        handover_for = "client"
        order.open_for_platform_claim = False

    if order.mode == "pickup":
        notify(
            env,
            partner=order.client_id or None,
            guest_phone=order.guest_phone if not order.client_id else None,
            title="Colis pret pour retrait",
            body=(
                f"Commande {order.code}: le fournisseur a initialise le retrait. "
                f"Presentez-vous au magasin puis cliquez 'Colis recu'."
            ),
            link=f"#order?id={order.id}",
        )
        msg = "Retrait initialise pour le CLIENT. En attente de la venue du client."
    else:
        notify(
            env,
            partner=order.client_id or None,
            guest_phone=order.guest_phone if not order.client_id else None,
            title="Colis pret",
            body=f"Commande {order.code}: le fournisseur a prepare le colis.",
            link=f"#order?id={order.id}",
        )
        if livreur:
            notify(
                env,
                partner=livreur,
                title="Colis pret a recuperer",
                body=(
                    f"Commande {order.code}: le fournisseur a initialise le retrait. "
                    f"Recuperez le colis puis confirmez 'Colis recu'."
                ),
                link="#livreur",
            )
            msg = f"Retrait initialise pour le LIVREUR boutique/assigne ({livreur.phone})."
        else:
            msg = (
                "Reception du colis initialisee. "
                "Aucun livreur boutique assigne : un livreur autonome de la plateforme "
                "peut s'attribuer la course, ou l'admin peut l'attribuer."
            )

    audit_row(
        env, lik_user, "SUPPLIER_INIT_HANDOVER", "Order", order.id,
        {
            "mode": order.mode,
            "handover_for": handover_for,
            "payment_status": order.payment_status,
            "open_for_platform_claim": order.open_for_platform_claim,
        },
    )
    return {
        "message": msg,
        "order": order_to_dict(env, order, detailed=True),
        "handover_for": handover_for,
        "open_for_platform_claim": bool(order.open_for_platform_claim),
        "status": "PICKUP_IN_PROGRESS",
    }


def available_orders(env, lik_user):
    """LK-CLM-02 — E48: claimable orders with claim_source."""
    Run = env["likdelivery.delivery.run"].sudo()
    assigned_ids = set(
        Run.search(
            [
                ("order_id", "!=", False),
                ("state", "!=", "CANCELLED"),
                ("livreur_id", "!=", False),
            ]
        ).mapped("order_id").ids
    )
    orders = env["likdelivery.order"].sudo().search(
        [("mode", "=", "delivery"), ("state", "not in", list(BLOCKED_STATES))],
        order="create_date desc",
    )
    livreur_id = lik_user.partner_id.id
    result = []
    for order in orders:
        if order.id in assigned_ids:
            continue
        pref_soc = order.preferred_societe_id.id or None
        open_platform = bool(order.open_for_platform_claim)
        if pref_soc and not open_platform:
            if livreur_id not in fleet_livreur_ids(env, pref_soc):
                continue
            d = order_to_dict(env, order)
            d["claimable"] = True
            d["claim_source"] = "societe"
            result.append(d)
            continue

        shop_ids = shop_livreur_ids(env, order.supplier_id.id)
        is_shop_livreur = livreur_id in shop_ids
        # Boutique orders: only associated livreurs (until opened to platform)
        if shop_ids and not open_platform and not is_shop_livreur:
            continue
        # Platform pool: only after supplier init
        if not is_shop_livreur:
            if not open_platform and not (not shop_ids and order.state == "PICKUP_IN_PROGRESS"):
                continue

        d = order_to_dict(env, order)
        d["claimable"] = True
        d["claim_source"] = "boutique" if is_shop_livreur and not open_platform else "plateforme"
        result.append(d)
    return result


def claim_order(env, lik_user, order):
    """LK-CLM-01 — E49: self-assignment with pool guards."""
    if not order.exists():
        raise OrderNotFound("Commande inconnue")
    livreur = lik_user.partner_id
    if lik_user.lik_role != "livreur" or not livreur.active:
        raise OrderForbidden("Livreur invalide")

    shop_ids = shop_livreur_ids(env, order.supplier_id.id)
    open_platform = bool(order.open_for_platform_claim)
    is_shop_livreur = livreur.id in shop_ids
    pref_soc = order.preferred_societe_id.id or None

    if pref_soc and not open_platform:
        if livreur.id not in fleet_livreur_ids(env, pref_soc):
            raise OrderForbidden(
                "Cette course est reservee a la societe de livraison choisie par le client."
            )
    elif shop_ids and not is_shop_livreur and not open_platform:
        raise OrderForbidden(
            "Cette course est reservee aux livreurs de la boutique. "
            "Attendez que le fournisseur ouvre la course a la plateforme, ou qu'un admin l'attribue."
        )

    if not pref_soc and not shop_ids and not open_platform and order.state != "PICKUP_IN_PROGRESS":
        raise ValueError(
            "Le fournisseur n'a pas encore initialise la reception du colis pour les livreurs plateforme."
        )

    run = assign_livreur_to_order(env, order, livreur, lik_user)
    if order.state in ("CREATED", "PREPARING", "PICKUP_IN_PROGRESS"):
        order.state = "PICKUP_IN_PROGRESS"
        try:
            apply_mission_status(env, run, "PICKUP_INITIATED", lik_user)
        except ValueError:
            pass
    return {
        "delivery_run_id": run.id,
        "otp": run.otp_code,
        "order_id": order.id,
        "order_code": order.code,
        "status": run.state,
        "message": "Mission prise en charge",
        "claim_source": (
            "societe" if pref_soc and not open_platform
            else ("boutique" if is_shop_livreur else "plateforme")
        ),
    }


def validate_delivery(env, data):
    """LK-MSN-07 — E55: public OTP/QR validation (ported as-is, LK-SEC-05)."""
    Run = env["likdelivery.delivery.run"].sudo()
    run = None
    if data.get("otp"):
        run = Run.search([("otp_code", "=", str(data.get("otp")).upper())], limit=1)
    if not run and data.get("qr_token"):
        run = Run.search([("qr_token", "=", data.get("qr_token"))], limit=1)
    if not run:
        raise ValueError("Code invalide")
    order = run.order_id or None
    if order and order.payment_method == "cash_on_delivery" and order.payment_status != "paid":
        raise ValueError(
            "Paiement a la livraison non confirme. "
            "Le livreur doit d'abord confirmer que le client a paye."
        )
    run.state = "DELIVERED"
    run.delivery_time = fields.Datetime.now()
    if order:
        order.state = "DELIVERED"
        credit_supplier_sale(env, order)
        notify(
            env,
            partner=order.client_id or None,
            guest_phone=order.guest_phone if not order.client_id else None,
            title="Livraison confirmee",
            body=f"Votre commande {order.code} a ete livree.",
            link=f"#/order?id={order.id}",
        )
        if run.livreur_id:
            credit_livreur_delivery(run.livreur_id, run.price)
    audit_row(env, {"role": "system"}, "VALIDATE_DELIVERY", "DeliveryRun", run.id)
    return {"message": "Livraison validee", "run_id": run.id}
