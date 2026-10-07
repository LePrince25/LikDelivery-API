"""Driver GPS endpoints (E53, E54) — LK-GEO-01."""

from odoo import http
from odoo.http import request

from odoo.addons.likdelivery_api_base.lib.envelope import (
    VALIDATION,
    api_endpoint,
    json_body,
    raise_error,
    require_fields,
    success_response,
)


class LikDriverLocationController(http.Controller):
    @http.route(
        "/api/v1/driver/location", type="http", auth="none", methods=["POST"], csrf=False
    )
    @api_endpoint(roles=("livreur",))
    def push_location(self):
        """Append-only GPS trail."""
        data = json_body()
        require_fields(data, "lat", "lon")
        request.env["likdelivery.driver.location"].sudo().create(
            {
                "livreur_id": request.lik_user.partner_id.id,
                "latitude": float(data["lat"]),
                "longitude": float(data["lon"]),
                "accuracy": data.get("accuracy"),
            }
        )
        return success_response({"message": "Position enregistree"})

    @http.route(
        "/api/v1/driver/location/<int:livreur_id>",
        type="http", auth="none", methods=["GET"], csrf=False,
    )
    @api_endpoint()
    def read_location(self, livreur_id):
        """Latest position of a driver — PUBLIC in the reference (LK-SEC-08,
        ported as-is). livreur_id = partner id."""
        location = request.env["likdelivery.driver.location"].sudo().search(
            [("livreur_id", "=", livreur_id)], order="recorded_at desc", limit=1
        )
        if not location:
            raise_error(VALIDATION, "Aucune position")
        return success_response(
            {
                "livreur_id": livreur_id,
                "latitude": location.latitude,
                "longitude": location.longitude,
                "accuracy": location.accuracy,
                "recorded_at": location.recorded_at.isoformat(),
            }
        )


class LikDriverAvailabilityController(http.Controller):
    @http.route(
        "/api/v1/driver/availability",
        type="http", auth="none", methods=["GET"], csrf=False,
    )
    @api_endpoint(roles=("livreur",))
    def availability_get(self):
        from odoo.addons.likdelivery_core.services import availability

        return success_response(
            availability.self_hours_payload(request.env, request.lik_user)
        )

    @http.route(
        "/api/v1/driver/availability",
        type="http", auth="none", methods=["POST"], csrf=False,
    )
    @api_endpoint(roles=("livreur",))
    def availability_post(self):
        from odoo.addons.likdelivery_core.services import availability

        data = json_body()
        items = data
        if isinstance(data, dict):
            items = data.get("hours") or data.get("items") or []
        try:
            result = availability.replace_opening_hours(
                request.env, request.lik_user, items
            )
        except ValueError as err:
            raise_error(VALIDATION, str(err))
        return success_response(result)
