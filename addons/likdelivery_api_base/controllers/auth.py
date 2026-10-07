import re

from odoo import http

from ..lib import jwt_auth
from ..lib.envelope import (
    AUTH_INVALID,
    CONFLICT,
    VALIDATION,
    anti_enumeration_delay,
    api_endpoint,
    audit,
    json_body,
    raise_error,
    require_fields,
    success_response,
)
from ..lib.jwt_auth import (
    auth_cookies,
    clear_auth_cookies,
    issue_tokens,
    revoke,
    rotate_tokens,
)
from ..lib.serializers import user_to_dict

PHONE_RE = re.compile(r"^\+?\d{8,15}$")  # LK-AUT-06

REGISTER_ROLES = ("client", "fournisseur", "livreur", "societe")  # LK-AUT-01


def tokens_payload(access, refresh):
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "Bearer",
        "expires_in": jwt_auth.ACCESS_TTL_SECONDS,
    }


class LikAuthController(http.Controller):
    """Shared role-agnostic auth endpoints (mirrors the reference's single
    /api/login for all roles)."""

    @http.route(
        "/api/v1/auth/login", type="http", auth="none", methods=["POST"], csrf=False
    )
    @api_endpoint(rate=("auth", 100, 60))
    def login(self):
        data = json_body()
        require_fields(data, "phone", "password")
        user = (
            http.request.env["likdelivery.user"]
            .sudo()
            .search([("phone", "=", data["phone"])], limit=1)
        )
        if not user or not user.check_password(data["password"]):
            anti_enumeration_delay()
            raise_error(AUTH_INVALID, "Telephone ou mot de passe incorrect")
        if not user.active:
            anti_enumeration_delay()
            raise_error(AUTH_INVALID, "Telephone ou mot de passe incorrect")
        access, refresh = issue_tokens(user)
        http.request.lik_user = user
        audit("LOGIN", "user", user.id)
        return success_response(
            {"user": user_to_dict(user), "tokens": tokens_payload(access, refresh)},
            cookies=auth_cookies(access, refresh),
        )

    @http.route(
        "/api/v1/auth/refresh", type="http", auth="none", methods=["POST"], csrf=False
    )
    @api_endpoint(rate=("auth", 100, 60))
    def refresh(self):
        data = json_body()
        token = data.get("refresh_token") or http.request.httprequest.cookies.get(
            jwt_auth.REFRESH_COOKIE
        )
        if not token:
            raise_error(AUTH_INVALID, "Jeton de rafraichissement manquant")
        user, access, refresh = rotate_tokens(token)
        return success_response(
            {"tokens": tokens_payload(access, refresh)},
            cookies=auth_cookies(access, refresh),
        )

    @http.route(
        "/api/v1/auth/logout",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
    )
    @api_endpoint(roles=())
    def logout(self):
        revoke(http.request.lik_user)
        return success_response(
            {"logged_out": True}, cookies=clear_auth_cookies()
        )

    @http.route("/api/v1/auth/me", type="http", auth="none", methods=["GET"], csrf=False)
    @api_endpoint(roles=())
    def me(self):
        return success_response({"user": user_to_dict(http.request.lik_user)})


class LikRegisterController(http.Controller):
    """Account registration (LK-AUT-01..04)."""

    @http.route(
        "/api/v1/auth/register",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
    )
    @api_endpoint(rate=("auth", 100, 60))
    def register(self):
        data = json_body()
        require_fields(data, "phone", "password", "role")
        role = data["role"]
        if role not in REGISTER_ROLES:
            raise_error(VALIDATION, "Role non autorise a l'inscription")
        if not PHONE_RE.match(data["phone"]):
            raise_error(VALIDATION, "Numero de telephone invalide")
        if role in ("fournisseur", "societe") and not data.get("company_name"):
            raise_error(VALIDATION, "company_name requis pour ce role")
        User = http.request.env["likdelivery.user"].sudo()
        if User.search_count([("phone", "=", data["phone"])]):
            raise_error(CONFLICT, "Telephone deja utilise")
        first = (data.get("first_name") or "").strip()
        last = (data.get("last_name") or "").strip()
        user = User.create(
            {
                "name": f"{first} {last}".strip() or data["phone"],
                "phone": data["phone"],
                "email": data.get("email") or None,
                "lik_role": role,
                "lik_first_name": first or None,
                "lik_last_name": last or None,
                "lik_company_name": (data.get("company_name") or "").strip() or None,
                "street": data.get("address") or None,
                # LK-AUT-03: KYC gate for fournisseur/societe
                "lik_validated_by_admin": role in ("client", "livreur"),
            }
        )
        user.set_password(data["password"])
        http.request.lik_user = user
        audit("REGISTER", "user", user.id, {"role": role})
        return success_response({"user": user_to_dict(user)}, status=201)


class LikProfileController(http.Controller):
    """Shared profile endpoint (E05, amendment: role-agnostic like auth)."""

    @http.route(
        "/api/v1/auth/profile", type="http", auth="none", methods=["GET"], csrf=False
    )
    @api_endpoint(roles=())
    def profile_get(self):
        from odoo.addons.likdelivery_core.services import profile

        return success_response(
            profile.profile_payload(http.request.env, http.request.lik_user)
        )

    @http.route(
        "/api/v1/auth/profile", type="http", auth="none", methods=["PUT"], csrf=False
    )
    @api_endpoint(roles=())
    def profile_put(self):
        from odoo.addons.likdelivery_core.services import profile

        try:
            result = profile.update_profile(
                http.request.env, http.request.lik_user, json_body()
            )
        except ValueError as err:
            raise_error(VALIDATION, str(err))
        return success_response({"message": "Profil mis a jour", "user": result})
