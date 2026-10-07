"""Admin statistics service — exact port of /api/admin/stats +
/api/admin/analytics (LK-ADM-01), quirks included (LK-SEC-09).

Reference: main/app.py lines 3375-3414.
"""

from datetime import datetime, timedelta


def stats(env):
    """LK-ADM-01 — 6 KPIs. Quirks ported: today_orders compares datetime
    >= date; total_revenue includes cancelled/failed orders."""
    User = env["likdelivery.user"].sudo()
    Order = env["likdelivery.order"].sudo()
    Run = env["likdelivery.delivery.run"].sudo()
    Courier = env["likdelivery.courier.request"].sudo()
    Partner = env["res.partner"].sudo()
    return {
        "users": User.search_count([]),
        "orders": Order.search_count([]),
        "delivery_runs": Run.search_count([]),
        "courier_requests": Courier.search_count([]),
        "pending_validation": Partner.search_count(
            [
                ("lik_role", "in", ["fournisseur", "societe"]),
                ("lik_validated_by_admin", "=", False),
            ]
        ),
        "today_orders": Order.search_count(
            [("create_date", ">=", datetime.utcnow().date())]
        ),
        "total_revenue": sum(Order.search([]).mapped("total")) or 0,
    }


def analytics(env):
    """Orders per day (14 d), status counts, top 5 suppliers by revenue."""
    Order = env["likdelivery.order"].sudo()
    start = datetime.utcnow() - timedelta(days=14)
    by_day = Order.read_group(
        [("create_date", ">=", start)],
        fields=["total:sum"],
        groupby=["create_date:day"],
    )
    orders_by_day = [
        {
            "day": g["create_date:day"],
            "count": g["create_date_count"],
            "total": g["total"] or 0,
        }
        for g in by_day
    ]
    by_status = Order.read_group([], fields=[], groupby=["state"])
    status_counts = {g["state"]: g["state_count"] for g in by_status}
    top = Order.read_group(
        [],
        fields=["total:sum"],
        groupby=["supplier_id"],
        orderby="total desc",
        limit=5,
    )
    top_suppliers = [
        {
            "name": (g["supplier_id"][1] if g["supplier_id"] else "—"),
            "orders": g["supplier_id_count"],
            "revenue": g["total"] or 0,
        }
        for g in top
    ]
    return {
        "orders_by_day": orders_by_day,
        "status_counts": status_counts,
        "top_suppliers": top_suppliers,
    }
