"""Sales history service (E40) — per-day supplier sales (product-only CA).

Exact port of main/app.py lines 1623-1707.
"""

from .order_lifecycle import order_to_dict


def sales_history(env, lik_user, supplier_id=None, date_from="", date_to=""):
    sid = lik_user.partner_id.id
    if lik_user.lik_role == "admin" and supplier_id:
        sid = int(supplier_id)

    orders = env["likdelivery.order"].sudo().search(
        [("supplier_id", "=", sid)], order="create_date desc"
    )

    days_map = {}
    for order in orders:
        if not order.create_date:
            continue
        day_key = order.create_date.strftime("%Y-%m-%d")
        if date_from and day_key < date_from:
            continue
        if date_to and day_key > date_to:
            continue
        bucket = days_map.get(day_key)
        if not bucket:
            bucket = {
                "date": day_key,
                "orders_count": 0,
                "delivered_count": 0,
                "cancelled_count": 0,
                "failed_count": 0,
                "product_total": 0.0,
                "delivery_total": 0.0,
                "grand_total": 0.0,
                "orders": [],
            }
            days_map[day_key] = bucket

        bucket["orders"].append(order_to_dict(env, order))
        bucket["orders_count"] += 1
        if order.state == "DELIVERED":
            bucket["delivered_count"] += 1
        elif order.state == "CANCELLED":
            bucket["cancelled_count"] += 1
        elif order.state == "FAILED":
            bucket["failed_count"] += 1

        # CA fournisseur = ventes produits uniquement (frais livraison = livreur)
        if order.state not in ("CANCELLED", "FAILED"):
            bucket["product_total"] += float(order.product_total or 0)
            bucket["delivery_total"] += float(order.delivery_fee or 0)  # info only
            bucket["grand_total"] += float(order.product_total or 0)

    days = [days_map[k] for k in sorted(days_map.keys(), reverse=True)]
    for d in days:
        d["product_total"] = round(d["product_total"], 0)
        d["delivery_total"] = round(d["delivery_total"], 0)
        d["grand_total"] = round(d["product_total"], 0)
        d["supplier_sales"] = d["product_total"]

    summary = {
        "days_count": len(days),
        "orders_count": sum(d["orders_count"] for d in days),
        "delivered_count": sum(d["delivered_count"] for d in days),
        "cancelled_count": sum(d["cancelled_count"] for d in days),
        "product_total": round(sum(d["product_total"] for d in days), 0),
        "delivery_total": round(sum(d["delivery_total"] for d in days), 0),
        "grand_total": round(sum(d["product_total"] for d in days), 0),
        "supplier_sales": round(sum(d["product_total"] for d in days), 0),
        "note": "CA boutique = prix des produits uniquement. Les frais de livraison appartiennent au livreur.",
    }
    supplier = env["res.partner"].sudo().browse(sid)
    wallet = None
    if supplier.exists():
        wallet = {
            "role": supplier.lik_role,
            "kind": "product_sales",
            "label": "Ventes produits",
            "earned": round(supplier.lik_wallet_earned, 0),
            "withdrawn": round(supplier.lik_wallet_withdrawn, 0),
            "available": supplier.lik_wallet_available,
            "balance": supplier.lik_wallet_available,
        }
    return {"summary": summary, "days": days, "wallet": wallet}
