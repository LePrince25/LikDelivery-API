"""Checkout service — preview + order creation.

preview() is an exact port of the reference /api/cart/checkout-preview
(LK-CHK-02). create_multi_orders / create_legacy_order /
create_order_with_payment / create_courier_request are exact ports of the
reference creation flows (LK-CHK-01/03/04/05, LK-PAY-01/02), quirks included.
Reference: main/app.py lines 430-449, 941-1040, 1176-1368, 1549-1601,
3093-3117.
"""

import secrets

from . import pricing
from .availability import supplier_availability
from .cart_service import cart_items
from .notification import notify
from ..models.lik_utils import generate_code

DEFAULT_DELIVERY_LAT = 6.16  # LK-PRC-05 — Lomé defaults
DEFAULT_DELIVERY_LON = 1.21

NOTES = {
    "pickup": "Retrait : uniquement le prix des produits (pas de frais de livraison).",
    "delivery_cod": "Livraison + paiement a la livraison : prix produits + frais de livraison.",
    "delivery_online": "Livraison + paiement mobile : prix produits + frais de livraison maintenant.",
}


def preview(env, lik_user, mode="delivery", payment_method="cash_on_delivery",
            delivery_lat=DEFAULT_DELIVERY_LAT, delivery_lon=DEFAULT_DELIVERY_LON):
    """LK-CHK-02 — per-supplier breakdown + totals.

    Raises ValueError('Panier vide') when the cart is empty.
    """
    items = cart_items(env, lik_user)
    if not items:
        raise ValueError("Panier vide")

    by_supplier = {}
    for item in items:
        by_supplier.setdefault(item.supplier_id.id, []).append(item)

    groups = []
    products_total = 0.0
    delivery_total = 0.0

    Partner = env["res.partner"].sudo()
    for supplier_id, supplier_items in by_supplier.items():
        supplier = Partner.search(
            [("id", "=", supplier_id), ("lik_role", "=", "fournisseur")], limit=1
        )
        ok, reason = supplier_availability(supplier)
        product_total = 0.0
        is_fragile = False
        lines = []
        for item in supplier_items:
            product = item.product_id
            if not product.exists() or not product.active:
                continue
            qty = min(item.quantity, product.stock)
            if qty <= 0:
                continue
            line_total = product.price * qty
            product_total += line_total
            if product.fragile:
                is_fragile = True
            lines.append(
                {
                    "product_id": product.id,
                    "name": product.name,
                    "quantity": qty,
                    "unit_price": product.price,
                    "line_total": line_total,
                }
            )
        # Quirk ported: high_value inspects every cart item that still exists,
        # even inactive / zero-stock ones (reference behavior).
        high_value = any(
            item.product_id.exists() and item.product_id.price > pricing.HIGH_VALUE_THRESHOLD
            for item in supplier_items
        )
        distance_km = 0.0
        delivery_fee = 0.0
        if mode == "delivery" and supplier and supplier.partner_latitude is not None:
            distance = pricing.haversine(
                supplier.partner_latitude,
                supplier.partner_longitude,
                delivery_lat,
                delivery_lon,
            )
            delivery_fee, distance_km = pricing.calculate_delivery_fee(
                distance, is_fragile=is_fragile, high_value=high_value
            )

        products_total += product_total
        delivery_total += delivery_fee
        groups.append(
            {
                "supplier_id": supplier_id,
                "supplier_name": (supplier.lik_company_name if supplier else None)
                or f"#{supplier_id}",
                "available": ok,
                "reason": reason,
                "lines": lines,
                "product_total": product_total,
                "distance_km": distance_km,
                "delivery_fee": delivery_fee,
                "subtotal": product_total + delivery_fee,
            }
        )

    grand_total = products_total + delivery_total
    amount_due_now = 0.0
    amount_due_on_delivery = 0.0
    if mode == "delivery" and payment_method == "cash_on_delivery":
        amount_due_on_delivery = grand_total  # produits + frais livraison
    elif mode == "pickup" and payment_method in ("cash_on_delivery", "pay_at_pickup"):
        amount_due_on_delivery = 0.0  # paye au magasin = produits only
    else:
        amount_due_now = grand_total

    return {
        "mode": mode,
        "payment_method": payment_method,
        "groups": groups,
        "products_total": products_total,
        "delivery_total": delivery_total,
        "grand_total": grand_total,
        "amount_due_now": amount_due_now,
        "amount_due_on_delivery": amount_due_on_delivery,
        "pay_now": amount_due_now > 0,
        "notes": NOTES,
    }


class CheckoutError(ValueError):
    """Business-level checkout failure (mapped to 400 by controllers)."""


def resolve_preferred_societe_id(env, data, lik_user, mode):
    """LK-CHK-05 — checkout param, else client profile fallback; must be an
    active validated société. Exact port of _resolve_preferred_societe_id."""
    if mode != "delivery":
        return None
    raw = data.get("preferred_societe_id", None)
    if raw in ("", None):
        if lik_user:
            raw = lik_user.lik_preferred_societe_id.id or None
        else:
            return None
    try:
        sid = int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None
    if not sid:
        return None
    soc = env["res.partner"].sudo().search(
        [
            ("id", "=", sid),
            ("lik_role", "=", "societe"),
            ("active", "=", True),
            ("lik_validated_by_admin", "=", True),
        ],
        limit=1,
    )
    return soc.id if soc else None


def create_multi_orders(env, lik_user, data):
    """LK-CHK-01/03 — one order per supplier from the server cart.

    Reference: POST /api/orders/multi. Raises CheckoutError with the
    reference French messages on validation failures.
    """
    mode = data.get("mode", "delivery")
    if mode not in ("delivery", "pickup"):
        raise CheckoutError("Mode invalide (delivery ou pickup)")

    payment_method = data.get("payment_method", "cash_on_delivery")
    if mode == "pickup":
        if payment_method == "cash_on_delivery":
            payment_method = "pay_at_pickup"
        delivery_address = None
        delivery_lat = None
        delivery_lon = None
    else:
        delivery_address = (data.get("delivery_address") or "").strip()
        if not delivery_address:
            raise CheckoutError("Adresse de livraison requise")
        delivery_lat = float(data.get("delivery_lat", DEFAULT_DELIVERY_LAT))
        delivery_lon = float(data.get("delivery_lon", DEFAULT_DELIVERY_LON))
        if payment_method == "pay_at_pickup":
            raise CheckoutError("Paiement au retrait impossible en mode livraison")

    items = cart_items(env, lik_user)
    if not items:
        raise CheckoutError("Panier vide")

    by_supplier = {}
    for item in items:
        by_supplier.setdefault(item.supplier_id.id, []).append(item)

    # Telephone saisi a la commande = contact destinataire (pour le livreur)
    payment_phone = (
        data.get("payment_phone") or data.get("guest_phone") or lik_user.phone or ""
    ).strip()
    if mode == "delivery" and not payment_phone:
        raise CheckoutError("Telephone du destinataire requis")

    preferred_societe_id = resolve_preferred_societe_id(env, data, lik_user, mode)

    Partner = env["res.partner"].sudo()
    Order = env["likdelivery.order"].sudo()
    Tx = env["likdelivery.payment.transaction"].sudo()

    orders = []
    skipped = []
    for supplier_id, supplier_items in by_supplier.items():
        supplier = Partner.search(
            [("id", "=", supplier_id), ("lik_role", "=", "fournisseur")], limit=1
        )
        ok, reason = supplier_availability(supplier)
        if not ok:
            skipped.append(reason or f"Fournisseur #{supplier_id} indisponible")
            continue
        order = Order.create(
            {
                "client_id": lik_user.partner_id.id,
                # guest_phone stocke le telephone de contact saisi au checkout
                "guest_phone": payment_phone or None,
                "supplier_id": supplier_id,
                "mode": mode,
                "delivery_address": delivery_address
                if mode == "delivery"
                else (supplier.street or "Retrait magasin"),
                "delivery_lat": delivery_lat,
                "delivery_lon": delivery_lon,
                "payment_method": payment_method,
                "is_fragile": False,
                "preferred_societe_id": preferred_societe_id,
            }
        )
        product_total = 0.0
        is_fragile = False
        for item in supplier_items:
            product = item.product_id
            if (
                not product.exists()
                or not product.active
                or product.supplier_id.id != supplier_id
            ):
                continue
            qty = min(item.quantity, product.stock)
            if qty <= 0:
                continue
            env["likdelivery.order.line"].sudo().create(
                {
                    "order_id": order.id,
                    "product_id": product.id,
                    "quantity": qty,
                    "unit_price": product.price,
                }
            )
            product_total += product.price * qty
            if product.fragile:
                is_fragile = True
            product.stock -= qty
        if product_total <= 0:
            order.unlink()
            skipped.append(
                f"{supplier.lik_company_name or supplier.phone} : "
                f"aucun article disponible (stock/actif)"
            )
            continue
        order.is_fragile = is_fragile
        order.product_total = product_total
        # Quirk ported: high_value inspects every cart item that still exists
        high_value = any(
            item.product_id.exists()
            and item.product_id.price > pricing.HIGH_VALUE_THRESHOLD
            for item in supplier_items
        )

        delivery_fee = 0.0
        if mode == "delivery" and supplier.partner_latitude is not None and delivery_lat is not None:
            distance = pricing.haversine(
                supplier.partner_latitude, supplier.partner_longitude,
                delivery_lat, delivery_lon,
            )
            delivery_fee, _ = pricing.calculate_delivery_fee(
                distance, is_fragile=is_fragile, high_value=high_value
            )

        # Total = prix produits + frais de livraison uniquement
        order.delivery_fee = delivery_fee
        order.total = order.product_total + order.delivery_fee

        # Immediate simulated payment unless COD / pay at pickup
        if payment_method not in ("cash_on_delivery", "pay_at_pickup"):
            Tx.create(
                {
                    "target_type": "order",
                    "order_id": order.id,
                    "amount": order.total,
                    "provider": payment_method,
                    "phone": payment_phone,
                    "state": "success",
                    # Reference uses token_hex(6).upper() here — no PROV- prefix
                    "provider_ref": secrets.token_hex(6).upper(),
                }
            )
            order.payment_status = "paid"
        else:
            order.payment_status = "pending"

        orders.append(
            {
                "order_id": order.id,
                "code": order.code,
                "total": order.total,
                "product_total": order.product_total,
                "delivery_fee": order.delivery_fee,
                "mode": mode,
                "payment_method": payment_method,
                "payment_status": order.payment_status,
                "supplier": supplier.lik_company_name,
            }
        )
        if payment_method == "cash_on_delivery":
            payment_label = (
                f"a payer a la livraison ({order.product_total:.0f} produits + "
                f"{delivery_fee:.0f} livraison = {order.total:.0f} XOF)"
            )
        elif payment_method == "pay_at_pickup":
            payment_label = f"a payer au retrait ({order.product_total:.0f} XOF)"
        else:
            payment_label = "payee"
        notify(
            env,
            partner=supplier,
            title=f"Nouvelle commande {'payee' if order.payment_status == 'paid' else ''}",
            body=f"Commande {order.code} — {mode} — {order.total:.0f} XOF ({payment_label}).",
            link="#supplier",
        )
        if preferred_societe_id:
            notify(
                env,
                partner=Partner.browse(preferred_societe_id),
                title="Nouvelle course a attribuer",
                body=(
                    f"Commande {order.code} vous a ete choisie par le client — "
                    f"{order.total:.0f} XOF."
                ),
                link="#societe",
            )

    if not orders:
        detail = " | ".join(skipped) if skipped else "Aucun fournisseur disponible"
        raise CheckoutError(f"Aucune commande creee. {detail}")

    cart_items(env, lik_user).unlink()
    return {
        "orders": orders,
        "count": len(orders),
        "skipped": skipped,
        "mode": mode,
        "payment_method": payment_method,
        "_audit": {
            "count": len(orders),
            "skipped": skipped,
            "mode": mode,
            "payment_method": payment_method,
        },
    }


def _create_legacy_order(env, lik_user, data, with_payment=False):
    """LK-CHK-04 — legacy single-supplier creation (strict stock, fragile-only
    fee). Shared by POST /api/orders and POST /api/orders/payment."""
    Partner = env["res.partner"].sudo()
    supplier_id = data.get("supplier_id")
    supplier = Partner.search(
        [("id", "=", supplier_id), ("lik_role", "=", "fournisseur")], limit=1
    )
    ok, reason = supplier_availability(supplier)
    if not ok:
        raise CheckoutError(reason or "Fournisseur indisponible")
    mode = data.get("mode", "delivery")
    lines = data.get("lines", [])
    if not lines:
        raise CheckoutError("Panier vide")

    payment_method = data.get("payment_method", "cash_on_delivery")
    payment_provider = data.get("payment_provider", payment_method)
    payment_phone = data.get(
        "payment_phone", (lik_user.phone if lik_user else data.get("guest_phone"))
    )
    simulate_payment_success = data.get("simulate_payment_success", True)

    Order = env["likdelivery.order"].sudo()
    order = Order.create(
        {
            "client_id": lik_user.partner_id.id if lik_user else None,
            "guest_phone": data.get("guest_phone") if not lik_user else None,
            "supplier_id": supplier_id,
            "mode": mode,
            "delivery_address": data.get("delivery_address") if mode == "delivery" else None,
            "delivery_lat": data.get("delivery_lat"),
            "delivery_lon": data.get("delivery_lon"),
            "payment_method": payment_method,
            "is_fragile": False,
        }
    )
    product_total = 0.0
    is_fragile = False
    for line in lines:
        product = env["likdelivery.product"].sudo().browse(line.get("product_id"))
        if (
            not product.exists()
            or product.supplier_id.id != supplier_id
            or not product.active
        ):
            continue
        qty = int(line.get("quantity", 1))
        if qty > product.stock:
            raise CheckoutError(f"Stock insuffisant pour {product.name}")
        env["likdelivery.order.line"].sudo().create(
            {
                "order_id": order.id,
                "product_id": product.id,
                "quantity": qty,
                "unit_price": product.price,
            }
        )
        product_total += product.price * qty
        if product.fragile:
            is_fragile = True
        product.stock -= qty
    order.is_fragile = is_fragile
    order.product_total = product_total
    delivery_fee = 0.0
    if mode == "delivery" and supplier.partner_latitude and data.get("delivery_lat"):
        distance = pricing.haversine(
            supplier.partner_latitude, supplier.partner_longitude,
            data.get("delivery_lat"), data.get("delivery_lon"),
        )
        delivery_fee, _ = pricing.calculate_legacy_fee(distance, is_fragile=is_fragile)
    order.delivery_fee = delivery_fee
    order.total = order.product_total + order.delivery_fee

    result = {
        "order_id": order.id,
        "code": order.code,
        "total": order.total,
        "otp": order.otp_code,
    }

    if with_payment:
        # Reference quirk ported: any method != cash_on_delivery creates a
        # transaction (pay_at_pickup included).
        payment_result = {"status": "pending", "provider": payment_provider}
        if payment_method != "cash_on_delivery":
            tx = env["likdelivery.payment.transaction"].sudo().create(
                {
                    "target_type": "order",
                    "order_id": order.id,
                    "amount": order.total,
                    "provider": payment_provider,
                    "phone": payment_phone,
                    "state": "pending",
                }
            )
            if simulate_payment_success:
                tx.state = "success"
                tx.provider_ref = generate_code("PROV-", 12)
                order.payment_status = "paid"
            else:
                tx.state = "failed"
                tx.failure_reason = "Paiement refuse (simulation)"
                order.payment_status = "failed"
            payment_result = {
                "status": tx.state,
                "reference": tx.reference,
                "provider": tx.provider,
                "provider_ref": tx.provider_ref or None,
            }
        result["payment"] = payment_result

    notify(
        env,
        partner=lik_user.partner_id if lik_user else None,
        guest_phone=data.get("guest_phone") if not lik_user else None,
        title="Commande creee",
        body=f"Votre commande {order.code} est enregistree. Total: {order.total:.0f} XOF.",
    )
    notify(
        env,
        partner=supplier,
        title="Nouvelle commande",
        body=f"Commande {order.code} de {order.total:.0f} XOF.",
        link="#/supplier",
    )
    return result


def create_legacy_order(env, lik_user, data):
    return _create_legacy_order(env, lik_user, data, with_payment=False)


def create_order_with_payment(env, lik_user, data):
    return _create_legacy_order(env, lik_user, data, with_payment=True)


def create_courier_request(env, lik_user, data):
    """LK-PRC-04 variant — standalone parcel run (stub lifecycle, LK-SEC-10).
    Reference: POST /api/courier-requests."""
    distance = pricing.haversine(
        data.get("pickup_lat"), data.get("pickup_lon"),
        data.get("dropoff_lat"), data.get("dropoff_lon"),
    )
    price = distance * pricing.PRICE_PER_KM
    if data.get("is_fragile"):
        price *= pricing.FRAGILE_BONUS
    req = env["likdelivery.courier.request"].sudo().create(
        {
            "client_id": lik_user.partner_id.id if lik_user else None,
            "guest_phone": data.get("guest_phone") if not lik_user else None,
            "pickup_address": data.get("pickup_address"),
            "pickup_lat": data.get("pickup_lat"),
            "pickup_lon": data.get("pickup_lon"),
            "dropoff_address": data.get("dropoff_address"),
            "dropoff_lat": data.get("dropoff_lat"),
            "dropoff_lon": data.get("dropoff_lon"),
            "distance_km": round(distance, 2),
            "price": round(price, 0),
            "is_fragile": bool(data.get("is_fragile")),
            "payment_method": data.get("payment_method", "cash_on_delivery"),
        }
    )
    notify(
        env,
        partner=lik_user.partner_id if lik_user else None,
        guest_phone=data.get("guest_phone") if not lik_user else None,
        title="Course colis creee",
        body=f"Votre course {req.code} est enregistree. Prix: {req.price:.0f} XOF.",
    )
    return {"id": req.id, "code": req.code, "price": req.price}
