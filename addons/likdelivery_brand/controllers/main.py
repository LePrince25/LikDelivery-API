import mimetypes

from odoo import http
from odoo.http import request
from odoo.tools import file_open

from odoo.addons.likos19_branding.controllers.main import LikOSHome

PWA_BASE = "likdelivery_brand/static/pwa"


def _pwa_response(relpath, extra_headers=None):
    """Serve a file from the bundled PWA directory (never traverses outside)."""
    if not relpath or ".." in relpath.split("/"):
        return request.not_found()
    path = "%s/%s" % (PWA_BASE, relpath)
    try:
        with file_open(path, "rb") as handle:
            content = handle.read()
    except (OSError, IOError):
        return request.not_found()
    mimetype = mimetypes.guess_type(relpath)[0] or "application/octet-stream"
    if relpath.endswith(".js"):
        mimetype = "application/javascript"
    headers = [("Content-Type", mimetype), ("X-Content-Type-Options", "nosniff")]
    headers.extend(extra_headers or [])
    return request.make_response(content, headers=headers)


class LikdeliveryPwaHome(LikOSHome):
    """Replace the Odoo landing page with the Livraison Express PWA shell."""

    @http.route()
    def index(self, s_action=None, db=None, **kw):
        return _pwa_response(
            "index.html",
            extra_headers=[("Cache-Control", "no-cache, max-age=0, must-revalidate")],
        )


class LikdeliveryPwaAssets(http.Controller):
    """Serve only the PWA static set at root scope; every other path falls
    through to the regular Odoo routing (/web, /api, /likos, /odoo, ...)."""

    @http.route(
        [
            "/js/<path:subpath>",
            "/css/<path:subpath>",
            "/images/<path:subpath>",
        ],
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
        readonly=True,
    )
    def pwa_assets(self, subpath, **kw):
        prefix = request.httprequest.path.split("/")[1]
        return _pwa_response("%s/%s" % (prefix, subpath))

    @http.route(
        "/manifest.json",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
        readonly=True,
    )
    def pwa_manifest(self, **kw):
        return _pwa_response("manifest.json")

    @http.route(
        "/service-worker.js",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
        readonly=True,
    )
    def pwa_service_worker(self, **kw):
        # Root scope: the PWA must control /, not just a sub-path.
        return _pwa_response(
            "service-worker.js",
            extra_headers=[
                ("Service-Worker-Allowed", "/"),
                ("Cache-Control", "no-cache, max-age=0, must-revalidate"),
            ],
        )
