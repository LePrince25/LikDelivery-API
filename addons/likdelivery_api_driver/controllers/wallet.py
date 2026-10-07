"""Driver wallet endpoints (E56, E57) — LK-WAL-03/04."""

from odoo import http
from odoo.http import request

from odoo.addons.likdelivery_core.services import wallet
from odoo.addons.likdelivery_api_base.lib.envelope import (
    VALIDATION,
    api_endpoint,
    audit,
    json_body,
    raise_error,
    success_response,
)


class LikDriverWalletController(http.Controller):
    @http.route(
        "/api/v1/driver/wallet", type="http", auth="none", methods=["GET"], csrf=False
    )
    @api_endpoint(roles=("livreur",))
    def wallet_get(self):
        return success_response(wallet.wallet_payload(request.env, request.lik_user))

    @http.route(
        "/api/v1/driver/wallet/withdraw",
        type="http", auth="none", methods=["POST"], csrf=False,
    )
    @api_endpoint(roles=("livreur",))
    def wallet_withdraw(self):
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
