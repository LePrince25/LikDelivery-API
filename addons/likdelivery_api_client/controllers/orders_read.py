"""Order read / lifecycle endpoints for the client namespace (E20, E21, E23)."""

from odoo import http
from odoo.http import request

from odoo.addons.likdelivery_core.services import (
    cancellation,
    order_lifecycle,
    rating,
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


def _browse_order(order_id):
    order = request.env["likdelivery.order"].sudo().browse(order_id)
    if not order.exists():
        raise_error(NOT_FOUND, "Commande inconnue")
    return order


class LikOrderReadController(http.Controller):
    @http.route(
        "/api/v1/client/orders", type="http", auth="none", methods=["GET"], csrf=False
    )
    @api_endpoint(roles=("client",))
    def orders_list(self):
        """LK-ORD-02 — own orders, newest first."""
        return success_response(
            order_lifecycle.list_orders_for(request.env, request.lik_user)
        )

    @http.route(
        "/api/v1/client/orders/<int:order_id>",
        type="http", auth="none", methods=["GET"], csrf=False,
    )
    @api_endpoint(roles=())
    def order_detail(self, order_id):
        """LK-ORD-03 — detailed view; visibility matrix enforced."""
        order = _browse_order(order_id)
        if not order_lifecycle.can_view_order(request.env, request.lik_user, order):
            raise_error(BOLA, "Acces refuse")
        return success_response(
            order_lifecycle.order_to_dict(request.env, order, detailed=True)
        )

    @http.route(
        "/api/v1/client/orders/<int:order_id>/pickup-action",
        type="http", auth="none", methods=["POST"], csrf=False,
    )
    @api_endpoint(roles=())
    def order_pickup_action(self, order_id):
        """LK-ORD-05 — init_pickup | confirm_received."""
        order = _browse_order(order_id)
        data = json_body()
        try:
            result = order_lifecycle.pickup_action(
                request.env, request.lik_user, order, data.get("action")
            )
        except order_lifecycle.OrderForbidden as err:
            raise_error(BOLA, str(err))
        except (order_lifecycle.OrderNotFound, ValueError) as err:
            raise_error(VALIDATION, str(err))
        action = (data.get("action") or "").strip().lower()
        audit_action = result.pop("_audit", None)
        if audit_action:
            audit(audit_action, "Order", order.id)
        elif action:
            audit(action.upper(), "Order", order.id)
        return success_response(result)


class LikOrderCancelRateController(http.Controller):
    @http.route(
        "/api/v1/client/orders/<int:order_id>/cancel",
        type="http", auth="none", methods=["POST"], csrf=False,
    )
    @api_endpoint()
    def order_cancel(self, order_id):
        """LK-CAN-01..04 — 80/20 penalty. Guest tolerated (gap LK-SEC-02
        ported as-is: ownership checked for clients only)."""
        lik_user = None
        try:
            from odoo.addons.likdelivery_api_base.lib import jwt_auth

            lik_user = jwt_auth.authenticate()
        except Exception:
            lik_user = None
        request.lik_user = lik_user
        order = request.env["likdelivery.order"].sudo().browse(order_id)
        try:
            result = cancellation.cancel_order(request.env, lik_user, order)
        except order_lifecycle.OrderNotFound as err:
            raise_error(NOT_FOUND, str(err))
        except order_lifecycle.OrderForbidden as err:
            raise_error(BOLA, str(err))
        except ValueError as err:
            raise_error(VALIDATION, str(err))
        return success_response(result)

    @http.route(
        "/api/v1/client/rate", type="http", auth="none", methods=["POST"], csrf=False
    )
    @api_endpoint(roles=("client",), rate=("rate", 10, 60))
    def rate(self):
        """LK-RAT-01/02 — 1–5 stars on own DELIVERED order / run."""
        try:
            result = rating.rate(request.env, request.lik_user, json_body())
        except order_lifecycle.OrderForbidden as err:
            raise_error(BOLA, str(err))
        except ValueError as err:
            raise_error(VALIDATION, str(err))
        return success_response(result)
