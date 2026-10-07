"""Merchant order endpoints (E38, E39, E41, E42)."""

from odoo import http
from odoo.http import request

from odoo.addons.likdelivery_core.services import assignment, order_lifecycle
from odoo.addons.likdelivery_core.services.order_lifecycle import (
    OrderForbidden,
    OrderNotFound,
)
from odoo.addons.likdelivery_api_base.lib.envelope import (
    BOLA,
    NOT_FOUND,
    VALIDATION,
    api_endpoint,
    audit,
    json_body,
    raise_error,
    success_response,
)


class LikMerchantOrderController(http.Controller):
    @http.route(
        "/api/v1/merchant/orders", type="http", auth="none", methods=["GET"], csrf=False
    )
    @api_endpoint(roles=("fournisseur", "societe", "admin"))
    def orders_list(self):
        """LK-ORD-02 / LK-SOC-06 — role-scoped list (fournisseur→own,
        societe→preferred, admin→all)."""
        return success_response(
            order_lifecycle.list_orders_for(request.env, request.lik_user)
        )

    @http.route(
        "/api/v1/merchant/orders/<int:order_id>/status",
        type="http", auth="none", methods=["POST"], csrf=False,
    )
    @api_endpoint(roles=("fournisseur", "admin"))
    def order_status(self, order_id):
        """LK-ORD-04 — arbitrary status set (reference behavior)."""
        order = request.env["likdelivery.order"].sudo().browse(order_id)
        if not order.exists():
            raise_error(NOT_FOUND, "Commande inconnue")
        data = json_body()
        try:
            result = order_lifecycle.update_order_status(
                request.env, request.lik_user, order, data.get("status")
            )
        except order_lifecycle.OrderForbidden as err:
            raise_error(BOLA, str(err))
        except (order_lifecycle.OrderNotFound, ValueError) as err:
            raise_error(VALIDATION, str(err))
        audit(
            "UPDATE_ORDER_STATUS", "Order", order.id,
            {"new_status": data.get("status")},
        )
        return success_response(result)


class LikMerchantAssignmentController(http.Controller):
    @http.route(
        "/api/v1/merchant/orders/<int:order_id>/init-handover",
        type="http", auth="none", methods=["POST"], csrf=False,
    )
    @api_endpoint(roles=("fournisseur", "societe", "admin"))
    def init_handover(self, order_id):
        """LK-ASN-04/05 — mark package ready (client / driver / platform)."""
        order = request.env["likdelivery.order"].sudo().browse(order_id)
        try:
            result = assignment.init_handover(request.env, request.lik_user, order)
        except OrderNotFound as err:
            raise_error(NOT_FOUND, str(err))
        except OrderForbidden as err:
            raise_error(BOLA, str(err))
        except ValueError as err:
            raise_error(VALIDATION, str(err))
        return success_response(result)

    @http.route(
        "/api/v1/merchant/orders/<int:order_id>/assign-driver",
        type="http", auth="none", methods=["POST"], csrf=False,
    )
    @api_endpoint(roles=("fournisseur", "societe", "admin"))
    def assign_driver(self, order_id):
        """LK-ASN-01/02 — assign a driver (shop pool / fleet / any for admin)."""
        order = request.env["likdelivery.order"].sudo().browse(order_id)
        data = json_body()
        try:
            result = assignment.assign_by_actor(
                request.env, request.lik_user, order, data.get("livreur_id")
            )
        except OrderNotFound as err:
            raise_error(NOT_FOUND, str(err))
        except OrderForbidden as err:
            raise_error(BOLA, str(err))
        except ValueError as err:
            raise_error(VALIDATION, str(err))
        return success_response(result)
