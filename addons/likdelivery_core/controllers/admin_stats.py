"""Admin dashboard page — back-office equivalent of /api/admin/stats +
/api/admin/analytics (D7)."""

from odoo import http
from odoo.http import request

from ..services import admin_stats

TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Livraison Express — Tableau de bord</title>
<style>
body {{ font-family: system-ui, sans-serif; background: #f3f4f6; margin: 24px; color: #111827; }}
h1 {{ color: #0b5fff; }} h2 {{ margin-top: 28px; }}
.cards {{ display: flex; flex-wrap: wrap; gap: 12px; }}
.card {{ background: #fff; border-radius: 10px; padding: 14px 20px; min-width: 170px;
        box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
.card b {{ font-size: 22px; display: block; }}
table {{ background: #fff; border-collapse: collapse; border-radius: 8px; overflow: hidden; }}
th, td {{ padding: 8px 14px; border-bottom: 1px solid #e5e7eb; text-align: left; }}
th {{ background: #0b5fff; color: #fff; }}
a.back {{ color: #0b5fff; }}
</style></head><body>
<p><a class="back" href="/web">← Back-office</a></p>
<h1>Tableau de bord</h1>
<div class="cards">
  <div class="card"><b>{users}</b>Utilisateurs</div>
  <div class="card"><b>{orders}</b>Commandes</div>
  <div class="card"><b>{delivery_runs}</b>Courses</div>
  <div class="card"><b>{courier_requests}</b>Courses colis</div>
  <div class="card"><b>{pending_validation}</b>Validations en attente</div>
  <div class="card"><b>{today_orders}</b>Commandes du jour</div>
  <div class="card"><b>{total_revenue:,.0f} XOF</b>Revenu total</div>
</div>
<h2>Commandes par jour (14 jours)</h2>
<table><tr><th>Jour</th><th>Commandes</th><th>Total</th></tr>{rows_day}</table>
<h2>Par statut</h2>
<table><tr><th>Statut</th><th>Nombre</th></tr>{rows_status}</table>
<h2>Top 5 fournisseurs</h2>
<table><tr><th>Fournisseur</th><th>Commandes</th><th>Revenu</th></tr>{rows_top}</table>
</body></html>"""


class LikAdminDashboard(http.Controller):
    @http.route("/likdelivery/admin/stats", type="http", auth="user")
    def dashboard(self):
        if not request.env.user.has_group("likdelivery_core.group_lik_admin"):
            return request.render("web.403") if False else request.redirect("/web")
        s = admin_stats.stats(request.env)
        a = admin_stats.analytics(request.env)
        rows_day = "".join(
            f"<tr><td>{r['day']}</td><td>{r['count']}</td><td>{r['total']:,.0f}</td></tr>"
            for r in a["orders_by_day"]
        )
        rows_status = "".join(
            f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in a["status_counts"].items()
        )
        rows_top = "".join(
            f"<tr><td>{r['name']}</td><td>{r['orders']}</td><td>{r['revenue']:,.0f}</td></tr>"
            for r in a["top_suppliers"]
        )
        return request.make_response(
            TEMPLATE.format(
                **s, rows_day=rows_day, rows_status=rows_status, rows_top=rows_top
            ),
            headers=[("Content-Type", "text/html; charset=utf-8")],
        )
