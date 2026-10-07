"""Cart & checkout-preview endpoints (E15, E16) — thin controllers (LK-CRT, LK-CHK-02)."""

from odoo import http
from odoo.http import request

from odoo.addons.likdelivery_core.services import cart_service, checkout
from odoo.addons.likdelivery_api_base.lib.envelope import (
    VALIDATION,
    ApiError,
    api_endpoint,
    json_body,
    raise_error,
    success_response,
)
from odoo.addons.likdelivery_api_base.lib import jwt_auth


class LikCartController(http.Controller):
    @http.route(
        "/api/v1/client/cart", type="http", auth="none", methods=["GET"], csrf=False
    )
    @api_endpoint()
    def cart_get(self, **params):
        """LK-CRT-01 — own cart when authenticated, guest token otherwise."""
        lik_user = None
        try:
            lik_user = jwt_auth.authenticate()
        except ApiError:
            lik_user = None  # guest mode (expired/invalid token ≈ anonymous)
        request.lik_user = lik_user
        return success_response(
            cart_service.cart_payload(
                request.env,
                lik_user=lik_user,
                session_token=params.get("session_token"),
            )
        )

    @http.route(
        "/api/v1/client/cart", type="http", auth="none", methods=["POST"], csrf=False
    )
    @api_endpoint(roles=())
    def cart_post(self):
        data = json_body()
        product_id = data.get("product_id")
        if not product_id:
            raise_error(VALIDATION, "product_id requis")
        try:
            quantity = int(data.get("quantity", 1))
            cart_service.add_to_cart(
                request.env, request.lik_user, int(product_id), quantity
            )
        except ValueError as err:
            raise_error(VALIDATION, str(err))
        return success_response({"message": "Panier mis a jour"})

    @http.route(
        "/api/v1/client/cart", type="http", auth="none", methods=["DELETE"], csrf=False
    )
    @api_endpoint(roles=())
    def cart_delete(self, **params):
        cart_service.clear_cart(
            request.env, request.lik_user, item_id=params.get("item_id")
        )
        return success_response({"message": "Panier vide"})

    @http.route(
        "/api/v1/client/cart/checkout-preview",
        type="http", auth="none", methods=["POST"], csrf=False,
    )
    @api_endpoint(roles=())
    def checkout_preview(self):
        """LK-CHK-02 — per-supplier totals; 400 when the cart is empty."""
        data = json_body()
        try:
            result = checkout.preview(
                request.env,
                request.lik_user,
                mode=data.get("mode", "delivery"),
                payment_method=data.get("payment_method", "cash_on_delivery"),
                delivery_lat=float(data.get("delivery_lat", checkout.DEFAULT_DELIVERY_LAT)),
                delivery_lon=float(data.get("delivery_lon", checkout.DEFAULT_DELIVERY_LON)),
            )
        except ValueError as err:
            raise_error(VALIDATION, str(err))
        return success_response(result)
