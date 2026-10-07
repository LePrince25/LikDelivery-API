"""Public catalog endpoints (E06–E14) — thin controllers.

All queries delegate to likdelivery_core services; serializers come from
likdelivery_api_base so every namespace emits identical shapes.
"""

from odoo import http
from odoo.http import request

from odoo.addons.likdelivery_core.services import availability, pricing, recommendation
from odoo.addons.likdelivery_api_base.lib.envelope import (
    NOT_FOUND,
    api_endpoint,
    json_body,
    raise_error,
    success_response,
)
from odoo.addons.likdelivery_api_base.lib.serializers import (
    category_to_dict,
    product_to_dict,
    societe_to_dict,
    supplier_to_dict,
    user_to_dict,
)

DEFAULT_DELIVERY_LAT = 6.16  # LK-PRC-05 — Lomé defaults
DEFAULT_DELIVERY_LON = 1.21


class LikCatalogController(http.Controller):
    @http.route(
        "/api/v1/client/catalog/categories",
        type="http", auth="none", methods=["GET"], csrf=False,
    )
    @api_endpoint()
    def categories(self):
        cats = request.env["likdelivery.product.category"].sudo().search([])
        return success_response([category_to_dict(c) for c in cats])

    @http.route(
        "/api/v1/client/catalog/suppliers",
        type="http", auth="none", methods=["GET"], csrf=False,
    )
    @api_endpoint()
    def suppliers(self):
        """LK-CAT-03 — active + validated fournisseurs with product_count,
        average_rating, open_now."""
        Partner = request.env["res.partner"].sudo()
        Product = request.env["likdelivery.product"].sudo()
        suppliers = Partner.search(
            [
                ("lik_role", "=", "fournisseur"),
                ("active", "=", True),
                ("lik_validated_by_admin", "=", True),
            ]
        )
        result = []
        for supplier in suppliers:
            count = Product.search_count(
                [("supplier_id", "=", supplier.id), ("active", "=", True)]
            )
            result.append(
                supplier_to_dict(supplier, count, availability.is_open_now(supplier))
            )
        return success_response(result)

    @http.route(
        "/api/v1/client/catalog/products",
        type="http", auth="none", methods=["GET"], csrf=False,
    )
    @api_endpoint()
    def products(self, **params):
        """LK-CAT-01/02 — active products; supplier_id / category_id /
        search (product name, description, supplier company) filters."""
        Product = request.env["likdelivery.product"].sudo()
        domain = [("active", "=", True)]
        if params.get("supplier_id"):
            domain.append(("supplier_id", "=", int(params["supplier_id"])))
        if params.get("category_id"):
            domain.append(("category_id", "=", int(params["category_id"])))
        search = (params.get("search") or "").strip()
        if search:
            term = ("ilike", search)
            domain += [
                "|",
                "|",
                ("name", *term),
                ("description", *term),
                ("supplier_id.lik_company_name", *term),
            ]
        products = Product.search(domain)
        open_cache = {}
        result = []
        for product in products:
            sid = product.supplier_id.id
            if sid not in open_cache:
                open_cache[sid] = availability.is_open_now(product.supplier_id)
            result.append(product_to_dict(product, open_now=open_cache[sid]))
        return success_response(result)

    @http.route(
        "/api/v1/client/catalog/products/<int:product_id>",
        type="http", auth="none", methods=["GET"], csrf=False,
    )
    @api_endpoint()
    def product_detail(self, product_id):
        product = request.env["likdelivery.product"].sudo().browse(product_id)
        if not product.exists() or not product.active:
            raise_error(NOT_FOUND, "Produit introuvable ou indisponible")
        result = product_to_dict(
            product, open_now=availability.is_open_now(product.supplier_id)
        )
        supplier = product.supplier_id
        if supplier:
            result["supplier_address"] = supplier.street or None
            result["supplier_phone"] = supplier.phone
            result["supplier_lat"] = supplier.partner_latitude or None
            result["supplier_lon"] = supplier.partner_longitude or None
        return success_response(result)

    @http.route(
        "/api/v1/client/catalog/suppliers/<int:user_id>/opening-hours",
        type="http", auth="none", methods=["GET"], csrf=False,
    )
    @api_endpoint()
    def opening_hours(self, user_id):
        partner = request.env["res.partner"].sudo().browse(user_id)
        if not partner.exists():
            raise_error(NOT_FOUND, "Utilisateur introuvable")
        return success_response(availability.opening_hours_payload(partner))

    @http.route(
        "/api/v1/client/catalog/societes",
        type="http", auth="none", methods=["GET"], csrf=False,
    )
    @api_endpoint()
    def societes(self):
        """LK-CAT-03 — validated sociétés with fleet_count, ordered by name."""
        Partner = request.env["res.partner"].sudo()
        Fleet = request.env["likdelivery.fleet.driver"].sudo()
        societes = Partner.search(
            [
                ("lik_role", "=", "societe"),
                ("active", "=", True),
                ("lik_validated_by_admin", "=", True),
            ],
            order="lik_company_name asc",
        )
        result = []
        for societe in societes:
            count = Fleet.search_count(
                [("societe_id", "=", societe.id), ("is_active", "=", True)]
            )
            result.append(societe_to_dict(societe, count))
        return success_response(result)

    @http.route(
        "/api/v1/client/catalog/livreurs",
        type="http", auth="none", methods=["GET"], csrf=False,
    )
    @api_endpoint()
    def livreurs(self, **params):
        min_rating = params.get("min_rating")
        partners = recommendation.list_livreurs(
            request.env,
            available_now=bool(params.get("available_now")),
            min_rating=float(min_rating) if min_rating else None,
        )
        lik_users = request.env["likdelivery.user"].sudo().search(
            [("partner_id", "in", partners.ids)]
        )
        return success_response([user_to_dict(u) for u in lik_users])

    @http.route(
        "/api/v1/client/catalog/recommended-livreurs",
        type="http", auth="none", methods=["GET"], csrf=False,
    )
    @api_endpoint()
    def recommended_livreurs(self, **params):
        """LK-REC-01 — night/high_value filters, rating order, limit 10."""
        partners = recommendation.recommended_livreurs(
            request.env,
            night=bool(params.get("night")),
            high_value=bool(params.get("high_value")),
        )
        lik_users = request.env["likdelivery.user"].sudo().search(
            [("partner_id", "in", partners.ids)]
        )
        by_partner = {u.partner_id.id: u for u in lik_users}
        return success_response(
            [user_to_dict(by_partner[p.id]) for p in partners if p.id in by_partner]
        )

    @http.route(
        "/api/v1/client/estimate-delivery",
        type="http", auth="none", methods=["POST"], csrf=False,
    )
    @api_endpoint()
    def estimate_delivery(self):
        """LK-PRC-06 — fee breakdown from request flags."""
        data = json_body()
        distance = pricing.haversine(
            data.get("from_lat"),
            data.get("from_lon"),
            data.get("to_lat"),
            data.get("to_lon"),
        )
        return success_response(
            pricing.estimate_breakdown(
                distance,
                fragile=bool(data.get("fragile")),
                night=bool(data.get("night")),
                high_value=bool(data.get("high_value")),
            )
        )
