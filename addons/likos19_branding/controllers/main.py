import base64

from odoo import http
from odoo.http import request
from odoo.addons.web.controllers.home import Home
from odoo.addons.web.controllers.session import Session
from odoo.addons.web.controllers.utils import ensure_db
from odoo.addons.web.controllers.webmanifest import WebManifest
from odoo.tools import file_open


LIKOS_ROOT = "/likos"
ODOO_ROOT = "/odoo"
APP_NAME_KEY = "APP_NAME"
DEFAULT_APP_NAME = "LikOS"


def _public_app_name():
    """Return the single configuration value that is safe to expose publicly."""
    value = request.env["ir.config_parameter"].sudo().get_param(APP_NAME_KEY)
    return (str(value).strip()[:160] if value else "") or DEFAULT_APP_NAME


def _branding_image_response(field_name):
    branding = request.env["likos.branding"].sudo().get_for_request()
    resolved = branding.resolve_image_field(field_name) if branding else field_name
    payload = branding[resolved] if branding else False
    filename = (
        (branding["%s_filename" % resolved] or resolved.replace("_", "-"))
        if branding and payload
        else "likos-logo.svg"
    )
    if payload:
        if isinstance(payload, bytes):
            try:
                raw = base64.b64decode(payload)
            except Exception:
                raw = payload
        else:
            raw = base64.b64decode(payload)
        mimetype = branding.image_mimetype(resolved)
    else:
        with file_open("likos19_branding/static/description/likos-logo.svg", "rb") as handle:
            raw = handle.read()
        mimetype = "image/svg+xml"
    if mimetype == "image/svg+xml":
        content_type = "image/svg+xml; charset=utf-8"
        filename = filename if str(filename).lower().endswith(".svg") else "%s.svg" % filename
        csp = "default-src 'none'; style-src 'unsafe-inline'; img-src data:"
    else:
        content_type = mimetype
        csp = "default-src 'none'"
    return request.make_response(
        raw,
        headers=[
            ("Content-Type", content_type),
            ("Content-Disposition", "inline; filename=%s" % filename),
            ("X-Content-Type-Options", "nosniff"),
            ("Content-Security-Policy", csp),
            ("Cache-Control", "no-cache, max-age=0, must-revalidate"),
        ],
    )


def _likos_url(url):
    """Translate only local Odoo web-client URLs to their LikOS equivalent."""
    if url == ODOO_ROOT or url.startswith(f"{ODOO_ROOT}/") or url.startswith(f"{ODOO_ROOT}?"):
        return f"{LIKOS_ROOT}{url[len(ODOO_ROOT):]}"
    return url


class LikOSHome(Home):
    @http.route()
    def index(self, s_action=None, db=None, **kw):
        response = super().index(s_action=s_action, db=db, **kw)
        if response.headers.get("Location"):
            response.headers["Location"] = _likos_url(response.headers["Location"])
        return response

    @http.route("/admin", type="http", auth="none", methods=["GET"], readonly=True)
    def legacy_admin(self, **kw):
        """Keep the former registry administration bookmark useful after cutover."""
        return request.redirect(LIKOS_ROOT, 303)

    @http.route()
    def web_client(self, s_action=None, **kw):
        request_path = request.httprequest.path
        if request_path == ODOO_ROOT or request_path.startswith(f"{ODOO_ROOT}/"):
            target = _likos_url(request.httprequest.full_path).removesuffix("?")
            return request.redirect(target, 303)
        return super().web_client(s_action=s_action, **kw)

    @http.route(
        ["/likos", "/likos/<path:subpath>"],
        type="http",
        auth="none",
        readonly=Home._web_client_readonly,
    )
    def likos_web_client(self, subpath=None, s_action=None, **kw):
        ensure_db()
        if not request.session.uid:
            query_string = request.httprequest.query_string.decode()
            target = request.httprequest.path
            if query_string:
                target = f"{target}?{query_string}"
            return request.redirect_query("/web/login", query={"redirect": target}, code=303)
        return super().web_client(s_action=s_action, **kw)

    @http.route()
    def web_login(self, redirect=None, **kw):
        return super().web_login(redirect=_likos_url(redirect) if redirect else redirect, **kw)

    def _login_redirect(self, uid, redirect=None):
        return _likos_url(super()._login_redirect(uid, redirect=redirect))


class LikOSSession(Session):
    @http.route()
    def logout(self, redirect=LIKOS_ROOT):
        return super().logout(redirect=_likos_url(redirect))


class LikOSPublicConfig(http.Controller):
    @http.route(
        "/likos/app-config",
        type="http",
        auth="public",
        methods=["GET"],
        save_session=False,
        readonly=True,
    )
    def app_config(self):
        branding = request.env["likos.branding"].sudo().get_for_request()
        version = branding.asset_version()
        response = request.make_json_response(
            {
                "app_name": _public_app_name(),
                "company_id": branding.company_id.id if branding.company_id else None,
                "favicon": f"/likos/branding/favicon?v={version}",
                "favicon_type": branding.public_image_mimetype("favicon"),
                "login_logo": f"/likos/branding/login-logo?v={version}",
                "login_logo_type": branding.public_image_mimetype("login_logo"),
                "app_logo": f"/likos/branding/app-logo?v={version}",
                "app_logo_type": branding.public_image_mimetype("app_logo"),
            }
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @http.route(
        "/likos/branding/favicon",
        type="http",
        auth="public",
        methods=["GET"],
        save_session=False,
        readonly=True,
        csrf=False,
    )
    def branding_favicon(self, **kwargs):
        return _branding_image_response("favicon")

    @http.route(
        "/likos/branding/login-logo",
        type="http",
        auth="public",
        methods=["GET"],
        save_session=False,
        readonly=True,
        csrf=False,
    )
    def branding_login_logo(self, **kwargs):
        return _branding_image_response("login_logo")

    @http.route(
        "/likos/branding/app-logo",
        type="http",
        auth="public",
        methods=["GET"],
        save_session=False,
        readonly=True,
        csrf=False,
    )
    def branding_app_logo(self, **kwargs):
        return _branding_image_response("app_logo")


class LikOSWebManifest(WebManifest):
    def _get_shortcuts(self):
        shortcuts = super()._get_shortcuts()
        for shortcut in shortcuts:
            shortcut["url"] = _likos_url(shortcut["url"])
        return shortcuts

    def _get_webmanifest(self):
        manifest = super()._get_webmanifest()
        branding = request.env["likos.branding"].sudo().get_for_request()
        app_logo_type = branding.public_image_mimetype("app_logo")
        manifest.update(
            {
                "name": _public_app_name(),
                "scope": LIKOS_ROOT,
                "start_url": LIKOS_ROOT,
                "background_color": "#edf2f8",
                "theme_color": "#13233d",
                "icons": [
                    {
                        "src": "/likos/branding/app-logo",
                        "sizes": "any",
                        "type": app_logo_type,
                    }
                ],
            }
        )
        return manifest

    @http.route()
    def service_worker(self):
        response = super().service_worker()
        response.headers["Service-Worker-Allowed"] = LIKOS_ROOT
        return response

    def _get_service_worker_content(self):
        return super()._get_service_worker_content().replace(ODOO_ROOT, LIKOS_ROOT)

    @http.route("/likos/offline", type="http", auth="public", methods=["GET"], readonly=True)
    def likos_offline(self):
        return super().offline()
