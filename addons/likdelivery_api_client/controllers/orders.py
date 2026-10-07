"""Order creation endpoints (E17–E19) + courier requests (E24).

Thin controllers — creation logic lives in likdelivery_core.services.checkout.
"""

import json

from odoo import http
from odoo.http import request

from odoo.addons.likdelivery_core.services import checkout
from odoo.addons.likdelivery_api_base.lib import idempotency, jwt_auth
from odoo.addons.likdelivery_api_base.lib.envelope import (
    VALIDATION,
    ApiError,
    api_endpoint,
    audit,
    json_body,
    raise_error,
    success_response,
)


def _optional_user():
    """Soft auth for guest-capable endpoints (orders, courier)."""
    try:
        user = jwt_auth.authenticate()
        request.lik_user = user
        return user
    except ApiError:
        request.lik_user = None
        return None


class LikOrderCreateController(http.Controller):
    @http.route(
        "/api/v1/client/orders/multi",
        type="http", auth="none", methods=["POST"], csrf=False,
    )
    @api_endpoint(roles=(), rate=("orders", 30, 60))
    def orders_multi(self):
        """LK-CHK-01/03 — one order per supplier. Idempotent via header."""
        endpoint = "/api/v1/client/orders/multi"
        replay = idempotency.find_replay(endpoint)
        if replay:
            status, body = replay
            return request.make_response(
                body,
                status=status,
                headers=[("Content-Type", "application/json"), idempotency.REPLAY_HEADER],
            )
        data = json_body()
        try:
            result = checkout.create_multi_orders(request.env, request.lik_user, data)
        except checkout.CheckoutError as err:
            raise_error(VALIDATION, str(err))
        audit_details = result.pop("_audit")
        audit("CREATE_MULTI_ORDERS", "Order", None, audit_details)
        body = json.dumps({"ok": True, "data": result}, default=str, ensure_ascii=False)
        idempotency.store_response(endpoint, 200, body)
        return request.make_response(
            body, status=200, headers=[("Content-Type", "application/json")]
        )

    @http.route(
        "/api/v1/client/orders",
        type="http", auth="none", methods=["POST"], csrf=False,
    )
    @api_endpoint(rate=("orders", 30, 60))
    def orders_create_legacy(self):
        """LK-CHK-04 — legacy single-supplier order (guest allowed)."""
        lik_user = _optional_user()
        data = json_body()
        try:
            with request.env.cr.savepoint():
                result = checkout.create_legacy_order(request.env, lik_user, data)
        except checkout.CheckoutError as err:
            raise_error(VALIDATION, str(err))
        audit(
            "CREATE_ORDER", "Order", result["order_id"],
            user=lik_user, actor_role=None if lik_user else "guest",
        )
        return success_response(result)

    @http.route(
        "/api/v1/client/orders/payment",
        type="http", auth="none", methods=["POST"], csrf=False,
    )
    @api_endpoint(rate=("orders", 30, 60))
    def orders_create_with_payment(self):
        """LK-CHK-04 — legacy order + immediate simulated payment."""
        lik_user = _optional_user()
        data = json_body()
        try:
            with request.env.cr.savepoint():
                result = checkout.create_order_with_payment(request.env, lik_user, data)
        except checkout.CheckoutError as err:
            raise_error(VALIDATION, str(err))
        audit(
            "CREATE_ORDER_WITH_PAYMENT", "Order", result["order_id"],
            user=lik_user, actor_role=None if lik_user else "guest",
        )
        return success_response(result)

    @http.route(
        "/api/v1/client/courier-requests",
        type="http", auth="none", methods=["POST"], csrf=False,
    )
    @api_endpoint(rate=("orders", 30, 60))
    def courier_request_create(self):
        """Standalone parcel request (guest allowed; stub lifecycle LK-SEC-10)."""
        lik_user = _optional_user()
        data = json_body()
        result = checkout.create_courier_request(request.env, lik_user, data)
        audit(
            "CREATE_COURIER_REQUEST", "CourierRequest", result["id"],
            user=lik_user, actor_role=None if lik_user else "guest",
        )
        return success_response(result)
