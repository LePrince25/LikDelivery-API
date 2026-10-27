"""Admin dashboard data — back-office equivalent of /api/admin/stats +
/api/admin/analytics (D7), consumed by the OWL client action.

The HTML page this replaced (/likdelivery/admin/stats) is gone: the dashboard
is rendered by likdelivery_core/static/src/views/dashboard/.
"""

from odoo import _, http
from odoo.exceptions import AccessError
from odoo.http import request

from ..services import admin_stats

DASHBOARD_GROUP = "likdelivery_core.group_lik_perm_dashboard"


def _day_label(value):
    """'2026-10-27 00:00:00' (or date/datetime) -> '27/10' for the chart axis."""
    if hasattr(value, "strftime"):
        return value.strftime("%d/%m")
    return value or ""


def _shape(stats, analytics, status_labels):
    stats = dict(stats)
    stats["total_revenue"] = round(stats.get("total_revenue") or 0.0, 0)
    series = [
        {
            "label": _day_label(row["day"]),
            "count": row["count"],
            "total": round(row["total"] or 0.0, 0),
        }
        for row in analytics["orders_by_day"]
    ]
    return {
        "stats": stats,
        "orders_by_day": series,
        "max_day_total": max([row["total"] for row in series] or [0]),
        "status_counts": analytics["status_counts"],
        "status_labels": status_labels,
        "top_suppliers": [
            {**row, "revenue": round(row["revenue"] or 0.0, 0)}
            for row in analytics["top_suppliers"]
        ],
    }


class LikDashboard(http.Controller):
    @http.route("/likdelivery/dashboard/data", type="json", auth="user")
    def data(self):
        if not request.env.user.has_group(DASHBOARD_GROUP):
            raise AccessError(_("Tableau de bord Livraison non autorisé."))
        state_field = request.env["likdelivery.order"]._fields["state"]
        return _shape(
            admin_stats.stats(request.env),
            admin_stats.analytics(request.env),
            dict(state_field.get_description(request.env)["selection"]),
        )
