"""Merchant driver-network endpoints: shop drivers (E37), fleet (E43–E45),
sales history (E40)."""

from odoo import http
from odoo.http import request

from odoo.addons.likdelivery_core.services import fleet, sales, wallet
from odoo.addons.likdelivery_core.services.order_lifecycle import OrderNotFound
from odoo.addons.likdelivery_api_base.lib.envelope import (
    CONFLICT,
    NOT_FOUND,
    VALIDATION,
    api_endpoint,
    audit,
    json_body,
    raise_error,
    success_response,
)


class LikMerchantDriverController(http.Controller):
    # ---------- Shop drivers (E37) ----------
    @http.route(
        "/api/v1/merchant/shop-drivers",
        type="http", auth="none", methods=["GET"], csrf=False,
    )
    @api_endpoint(roles=("fournisseur", "societe", "admin"))
    def shop_drivers_list(self, **params):
        return success_response(
            fleet.shop_drivers_list(
                request.env, request.lik_user, supplier_id=params.get("supplier_id")
            )
        )

    @http.route(
        "/api/v1/merchant/shop-drivers",
        type="http", auth="none", methods=["POST"], csrf=False,
    )
    @api_endpoint(roles=("fournisseur", "societe", "admin"))
    def shop_drivers_link(self):
        data = json_body()
        try:
            result = fleet.shop_driver_link(
                request.env, request.lik_user,
                data.get("livreur_id"), supplier_id=data.get("supplier_id"),
            )
        except ValueError as err:
            raise_error(VALIDATION, str(err))
        return success_response(result)

    @http.route(
        "/api/v1/merchant/shop-drivers",
        type="http", auth="none", methods=["DELETE"], csrf=False,
    )
    @api_endpoint(roles=("fournisseur", "societe", "admin"))
    def shop_drivers_unlink(self, **params):
        data = json_body()
        livreur_id = data.get("livreur_id") or params.get("livreur_id")
        try:
            result = fleet.shop_driver_unlink(
                request.env, request.lik_user, livreur_id,
                supplier_id=data.get("supplier_id") or params.get("supplier_id"),
            )
        except OrderNotFound as err:
            raise_error(NOT_FOUND, str(err))
        return success_response(result)


class LikMerchantFleetController(http.Controller):
    # ---------- Société fleet (E43–E45) ----------
    @http.route(
        "/api/v1/merchant/fleet/drivers",
        type="http", auth="none", methods=["GET"], csrf=False,
    )
    @api_endpoint(roles=("societe", "admin"))
    def fleet_list(self, **params):
        try:
            result = fleet.fleet_list(request.env, request.lik_user, args=params)
        except ValueError as err:
            raise_error(VALIDATION, str(err))
        return success_response(result)

    @http.route(
        "/api/v1/merchant/fleet/drivers",
        type="http", auth="none", methods=["POST"], csrf=False,
    )
    @api_endpoint(roles=("societe", "admin"))
    def fleet_post(self):
        """create internal {create:true,...} or link external {livreur_id}."""
        data = json_body()
        try:
            if data.get("create") or data.get("mode") == "create_internal":
                result = fleet.fleet_create_internal(request.env, request.lik_user, data)
                status = result.pop("_status", 201)
                return success_response(result, status=status)
            result = fleet.fleet_link_external(request.env, request.lik_user, data)
        except FileExistsError as err:
            raise_error(CONFLICT, str(err))
        except OrderNotFound as err:
            raise_error(NOT_FOUND, str(err))
        except ValueError as err:
            raise_error(VALIDATION, str(err))
        return success_response(result)

    @http.route(
        "/api/v1/merchant/fleet/drivers",
        type="http", auth="none", methods=["DELETE"], csrf=False,
    )
    @api_endpoint(roles=("societe", "admin"))
    def fleet_unlink(self, **params):
        data = json_body()
        livreur_id = data.get("livreur_id") or params.get("livreur_id")
        try:
            result = fleet.fleet_unlink(
                request.env, request.lik_user, livreur_id, data=data, args=params
            )
        except OrderNotFound as err:
            raise_error(NOT_FOUND, str(err))
        except ValueError as err:
            raise_error(VALIDATION, str(err))
        return success_response(result)

    @http.route(
        "/api/v1/merchant/fleet/drivers/<int:livreur_id>",
        type="http", auth="none", methods=["PUT"], csrf=False,
    )
    @api_endpoint(roles=("societe", "admin"))
    def fleet_update(self, livreur_id):
        try:
            result = fleet.fleet_update_livreur(
                request.env, request.lik_user, livreur_id, json_body()
            )
        except OrderNotFound as err:
            raise_error(NOT_FOUND, str(err))
        except ValueError as err:
            raise_error(VALIDATION, str(err))
        return success_response(result)

    @http.route(
        "/api/v1/merchant/fleet/orders",
        type="http", auth="none", methods=["GET"], csrf=False,
    )
    @api_endpoint(roles=("societe", "admin"))
    def fleet_orders(self, **params):
        """LK-SOC-06 — ?status=open or exact status."""
        return success_response(
            fleet.societe_orders(request.env, request.lik_user, args=params)
        )


class LikMerchantSalesController(http.Controller):
    @http.route(
        "/api/v1/merchant/sales-history",
        type="http", auth="none", methods=["GET"], csrf=False,
    )
    @api_endpoint(roles=("fournisseur", "admin"))
    def sales_history(self, **params):
        """Per-day sales; CA = product prices only (?from&to, admin ?supplier_id)."""
        return success_response(
            sales.sales_history(
                request.env, request.lik_user,
                supplier_id=params.get("supplier_id"),
                date_from=(params.get("from") or "").strip(),
                date_to=(params.get("to") or "").strip(),
            )
        )


class LikMerchantWalletController(http.Controller):
    @http.route(
        "/api/v1/merchant/wallet", type="http", auth="none", methods=["GET"], csrf=False
    )
    @api_endpoint(roles=("fournisseur",))
    def wallet_get(self):
        """LK-WAL-03 — snapshot + last 50 withdrawals."""
        return success_response(wallet.wallet_payload(request.env, request.lik_user))

    @http.route(
        "/api/v1/merchant/wallet/withdraw",
        type="http", auth="none", methods=["POST"], csrf=False,
    )
    @api_endpoint(roles=("fournisseur",))
    def wallet_withdraw(self):
        """LK-WAL-04 — instant withdrawal (completed)."""
        data = json_body()
        try:
            result = wallet.withdraw(
                request.env, request.lik_user,
                data.get("amount"), note=data.get("note"),
            )
        except ValueError as err:
            raise_error(VALIDATION, str(err))
        details = result.pop("_audit")
        audit(
            "WALLET_WITHDRAW", "WalletWithdrawal", details["id"],
            {"amount": details["amount"], "kind": details["kind"]},
        )
        return success_response(result)
