"""Client notification endpoints (E30, E31) + payment endpoints (E26–E29)."""

from odoo import http
from odoo.http import request

from odoo.addons.likdelivery_core.services import notification, payment_service
from odoo.addons.likdelivery_core.services.order_lifecycle import OrderNotFound
from odoo.addons.likdelivery_api_base.lib import jwt_auth
from odoo.addons.likdelivery_api_base.lib.envelope import (
    NOT_FOUND,
    ApiError,
    api_endpoint,
    json_body,
    raise_error,
    success_response,
)


class LikNotificationController(http.Controller):
    @http.route(
        "/api/v1/client/notifications",
        type="http", auth="none", methods=["GET"], csrf=False,
    )
    @api_endpoint(roles=())
    def notifications_list(self):
        """LK-NOT-01 — own notifications, last 50."""
        return success_response(
            notification.list_for(request.env, request.lik_user)
        )

    @http.route(
        "/api/v1/client/notifications/<int:note_id>/read",
        type="http", auth="none", methods=["POST"], csrf=False,
    )
    @api_endpoint(roles=())
    def notifications_read(self, note_id):
        return success_response(
            notification.mark_read(request.env, request.lik_user, note_id)
        )


class LikPaymentController(http.Controller):
    @http.route(
        "/api/v1/client/payments/initiate",
        type="http", auth="none", methods=["POST"], csrf=False,
    )
    @api_endpoint()
    def payments_initiate(self):
        lik_user = _soft_user()
        try:
            result = payment_service.initiate(request.env, lik_user, json_body())
        except OrderNotFound as err:
            raise_error(NOT_FOUND, str(err))
        return success_response(result)

    @http.route(
        "/api/v1/client/payments/<string:reference>/status",
        type="http", auth="none", methods=["GET"], csrf=False,
    )
    @api_endpoint()
    def payments_status(self, reference):
        try:
            result = payment_service.status(request.env, reference)
        except OrderNotFound as err:
            raise_error(NOT_FOUND, str(err))
        return success_response(result)

    @http.route(
        "/api/v1/client/payments/<string:reference>/confirm",
        type="http", auth="none", methods=["POST"], csrf=False,
    )
    @api_endpoint()
    def payments_confirm(self, reference):
        """Simulated PSP webhook (LK-SEC-04 ported)."""
        lik_user = _soft_user()
        try:
            result = payment_service.confirm(
                request.env, lik_user, reference, json_body()
            )
        except OrderNotFound as err:
            raise_error(NOT_FOUND, str(err))
        return success_response(result)

    @http.route(
        "/api/v1/client/payments/simulate",
        type="http", auth="none", methods=["POST"], csrf=False,
    )
    @api_endpoint()
    def payments_simulate(self):
        """Legacy alias: confirm when reference given, else initiate."""
        lik_user = _soft_user()
        data = json_body()
        try:
            if data.get("reference"):
                result = payment_service.confirm(
                    request.env, lik_user, data["reference"], data
                )
            else:
                result = payment_service.initiate(request.env, lik_user, data)
        except OrderNotFound as err:
            raise_error(NOT_FOUND, str(err))
        return success_response(result)


def _soft_user():
    try:
        user = jwt_auth.authenticate()
        request.lik_user = user
        return user
    except ApiError:
        request.lik_user = None
        return None
