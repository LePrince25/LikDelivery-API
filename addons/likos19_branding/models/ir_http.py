from odoo import models
from odoo.http import request


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    def session_info(self):
        info = super().session_info()
        branding = request.env["likos.branding"].sudo().get_for_request()
        version = branding.asset_version()
        app_name = (
            request.env["ir.config_parameter"].sudo().get_param("APP_NAME") or "LikOS"
        )
        info["likos_branding"] = {
            "app_name": app_name,
            "company_id": branding.company_id.id if branding.company_id else None,
            "favicon": f"/likos/branding/favicon?v={version}",
            "favicon_type": branding.public_image_mimetype("favicon"),
            "login_logo": f"/likos/branding/login-logo?v={version}",
            "login_logo_type": branding.public_image_mimetype("login_logo"),
            "app_logo": f"/likos/branding/app-logo?v={version}",
            "app_logo_type": branding.public_image_mimetype("app_logo"),
        }
        return info
