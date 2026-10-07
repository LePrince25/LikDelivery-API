"""Driver mission endpoints (E48–E52, E55)."""

from odoo import http
from odoo.http import request

from odoo.addons.likdelivery_core.services import assignment, mission_lifecycle
from odoo.addons.likdelivery_core.services.order_lifecycle import (
    OrderForbidden,
    OrderNotFound,
)
from odoo.addons.likdelivery_api_base.lib.envelope import (
    BOLA,
    NOT_FOUND,
    VALIDATION,
    api_endpoint,
    json_body,
    raise_error,
    success_response,
)

ACTION_TO_STATUS = {
    "start": "STARTED",
    "init_pickup": "PICKUP_INITIATED",
    "confirm_received": "PICKED_UP",
    "pickup": "PICKED_UP",  # alias "colis recu"
    "en_route": "IN_TRANSIT",
    "deliver": "DELIVERED",
    "cancel": "CANCELLED",
}
ACTION_MESSAGES = {
    "start": "Course demarree. Rendez-vous chez le fournisseur.",
    "init_pickup": "Recuperation initialisee. Confirmez 'Colis recu' quand le colis est en main.",
    "confirm_received": "Colis recu confirme.",
    "pickup": "Colis recu confirme.",
    "en_route": "En route vers le client.",
    "deliver": "Livraison confirmee.",
    "cancel": "Course annulee.",
}


def _own_run(run_id):
    run = (
        request.env["likdelivery.delivery.run"]
        .sudo()
        .search(
            [("id", "=", run_id), ("livreur_id", "=", request.lik_user.partner_id.id)],
            limit=1,
        )
    )
    if not run:
        raise_error(NOT_FOUND, "Mission inconnue")
    return run


class LikDriverMissionController(http.Controller):
    @http.route(
        "/api/v1/driver/available-orders",
        type="http", auth="none", methods=["GET"], csrf=False,
    )
    @api_endpoint(roles=("livreur",))
    def available_orders(self):
        """LK-CLM-02 — claimable orders with claim_source."""
        return success_response(
            assignment.available_orders(request.env, request.lik_user)
        )

    @http.route(
        "/api/v1/driver/orders/<int:order_id>/claim",
        type="http", auth="none", methods=["POST"], csrf=False,
    )
    @api_endpoint(roles=("livreur",))
    def claim_order(self, order_id):
        """LK-CLM-01 — self-assignment with pool guards."""
        order = request.env["likdelivery.order"].sudo().browse(order_id)
        try:
            result = assignment.claim_order(request.env, request.lik_user, order)
        except OrderNotFound as err:
            raise_error(NOT_FOUND, str(err))
        except OrderForbidden as err:
            raise_error(BOLA, str(err))
        except ValueError as err:
            raise_error(VALIDATION, str(err))
        return success_response(result)

    @http.route(
        "/api/v1/driver/missions", type="http", auth="none", methods=["GET"], csrf=False
    )
    @api_endpoint(roles=("livreur",))
    def missions(self):
        """Own runs, newest first, with labels + next_action."""
        runs = request.env["likdelivery.delivery.run"].sudo().search(
            [("livreur_id", "=", request.lik_user.partner_id.id)],
            order="create_date desc",
        )
        return success_response(
            [mission_lifecycle.mission_dict(request.env, r) for r in runs]
        )

    @http.route(
        "/api/v1/driver/missions/<int:run_id>/status",
        type="http", auth="none", methods=["POST"], csrf=False,
    )
    @api_endpoint(roles=("livreur",))
    def mission_status(self, run_id):
        """LK-MSN-02 — direct status change (transition-validated)."""
        run = _own_run(run_id)
        data = json_body()
        try:
            mission_lifecycle.apply_mission_status(
                request.env, run, data.get("status"), request.lik_user,
                otp=data.get("otp"),
            )
        except ValueError as err:
            raise_error(VALIDATION, str(err))
        result = mission_lifecycle.mission_dict(request.env, run)
        result["message"] = "Mission mise a jour"
        return success_response(result)

    @http.route(
        "/api/v1/driver/missions/<int:run_id>/action",
        type="http", auth="none", methods=["POST"], csrf=False,
    )
    @api_endpoint(roles=("livreur",))
    def mission_action(self, run_id):
        """Action aliases + confirm_cod_payment."""
        run = _own_run(run_id)
        data = json_body()
        action = (data.get("action") or "").strip().lower()
        allowed = list(ACTION_TO_STATUS.keys()) + ["confirm_cod_payment"]
        if action not in allowed:
            raise_error(VALIDATION, "Action invalide")
        try:
            if action == "confirm_cod_payment":
                result = mission_lifecycle.confirm_cod_payment(
                    request.env, request.lik_user, run
                )
                return success_response(result)
            mission_lifecycle.apply_mission_status(
                request.env, run, ACTION_TO_STATUS[action], request.lik_user,
                otp=data.get("otp"),
            )
        except ValueError as err:
            raise_error(VALIDATION, str(err))
        result = mission_lifecycle.mission_dict(request.env, run)
        result["message"] = ACTION_MESSAGES.get(action, "OK")
        return success_response(result)

    @http.route(
        "/api/v1/driver/validate-delivery",
        type="http", auth="none", methods=["POST"], csrf=False,
    )
    @api_endpoint()
    def validate_delivery(self):
        """LK-MSN-07 — public OTP/QR validation (ported as-is, LK-SEC-05)."""
        try:
            result = assignment.validate_delivery(request.env, json_body())
        except ValueError as err:
            raise_error(VALIDATION, str(err))
        return success_response(result)
