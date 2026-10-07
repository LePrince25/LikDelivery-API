"""Merchant settings endpoints: opening hours (E35) + KYC (E36)."""

from odoo import http
from odoo.http import request

from odoo.addons.likdelivery_core.services import availability, kyc
from odoo.addons.likdelivery_api_base.lib.envelope import (
    VALIDATION,
    api_endpoint,
    json_body,
    raise_error,
    success_response,
)


class LikMerchantSettingsController(http.Controller):
    @http.route(
        "/api/v1/merchant/opening-hours",
        type="http", auth="none", methods=["GET"], csrf=False,
    )
    @api_endpoint(roles=("fournisseur", "livreur", "societe", "admin"))
    def hours_get(self):
        return success_response(
            availability.self_hours_payload(request.env, request.lik_user)
        )

    @http.route(
        "/api/v1/merchant/opening-hours",
        type="http", auth="none", methods=["POST"], csrf=False,
    )
    @api_endpoint(roles=("fournisseur", "livreur", "societe", "admin"))
    def hours_post(self):
        """LK-HRS-01 — replaces ALL hours; list or {hours: [...]}."""
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

    @http.route(
        "/api/v1/merchant/kyc", type="http", auth="none", methods=["POST"], csrf=False
    )
    @api_endpoint(roles=("fournisseur", "societe", "admin"))
    def kyc_upload(self):
        """LK-KYC-01 — multipart id_document (required) + cfe_document."""
        files = request.httprequest.files
        if "id_document" not in files or not files["id_document"].filename:
            raise_error(VALIDATION, "Piece d'identite requise")
        id_upload = files["id_document"]
        cfe_upload = files.get("cfe_document")
        try:
            result = kyc.upload_kyc(
                request.env,
                request.lik_user,
                (id_upload.filename, id_upload.read()),
                (cfe_upload.filename, cfe_upload.read()) if cfe_upload else None,
            )
        except ValueError as err:
            raise_error(VALIDATION, str(err))
        return success_response(result)
