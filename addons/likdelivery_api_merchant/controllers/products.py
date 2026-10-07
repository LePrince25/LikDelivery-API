"""Merchant product endpoints (E32–E34)."""

from odoo import http
from odoo.http import request

from odoo.addons.likdelivery_core.services import catalog
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


class LikMerchantProductController(http.Controller):
    @http.route(
        "/api/v1/merchant/products", type="http", auth="none", methods=["GET"], csrf=False
    )
    @api_endpoint(roles=("fournisseur", "admin"))
    def products_list(self):
        return success_response(catalog.list_products(request.env, request.lik_user))

    @http.route(
        "/api/v1/merchant/products", type="http", auth="none", methods=["POST"], csrf=False
    )
    @api_endpoint(roles=("fournisseur", "admin"))
    def products_create(self):
        result = catalog.create_product(request.env, request.lik_user, json_body())
        return success_response(result, status=201)

    @http.route(
        "/api/v1/merchant/products/<int:product_id>",
        type="http", auth="none", methods=["PUT"], csrf=False,
    )
    @api_endpoint(roles=("fournisseur", "admin"))
    def products_update(self, product_id):
        try:
            result = catalog.update_product(
                request.env, request.lik_user, product_id, json_body()
            )
        except OrderNotFound as err:
            raise_error(NOT_FOUND, str(err))
        except OrderForbidden as err:
            raise_error(BOLA, str(err))
        return success_response(result)

    @http.route(
        "/api/v1/merchant/products/<int:product_id>",
        type="http", auth="none", methods=["DELETE"], csrf=False,
    )
    @api_endpoint(roles=("fournisseur", "admin"))
    def products_delete(self, product_id):
        try:
            result = catalog.delete_product(request.env, request.lik_user, product_id)
        except OrderNotFound as err:
            raise_error(NOT_FOUND, str(err))
        except OrderForbidden as err:
            raise_error(BOLA, str(err))
        return success_response(result)

    @http.route(
        "/api/v1/merchant/products/<int:product_id>/image",
        type="http", auth="none", methods=["POST"], csrf=False,
    )
    @api_endpoint(roles=("fournisseur", "admin", "societe"))
    def products_image(self, product_id):
        """LK-UPL-01 — multipart field 'image', ext whitelist, 5 MB cap
        (MAX_CONTENT_LENGTH equivalent set server-side)."""
        files = request.httprequest.files
        if "image" not in files:
            raise_error(VALIDATION, "Aucun fichier image (champ 'image')")
        upload = files["image"]
        content = upload.read()
        if len(content) > 5 * 1024 * 1024:
            raise_error(VALIDATION, "Fichier trop volumineux (max 5 Mo)")
        try:
            result = catalog.upload_product_image(
                request.env, request.lik_user, product_id, upload.filename, content
            )
        except OrderNotFound as err:
            raise_error(NOT_FOUND, str(err))
        except OrderForbidden as err:
            raise_error(BOLA, str(err))
        except ValueError as err:
            raise_error(VALIDATION, str(err))
        return success_response(result)
