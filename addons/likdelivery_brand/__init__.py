import base64

from odoo.tools import file_open

from . import controllers


def _post_init_brand(env):
    """Freeze the Livraison Express identity on the existing branding rows.

    likos19_branding already created one likos.branding per company (unique
    constraint on company_id), so we update in place instead of creating.
    """
    with file_open("likdelivery_brand/static/description/icon.svg", "rb") as handle:
        icon_b64 = base64.b64encode(handle.read())
    Branding = env["likos.branding"].sudo()
    for company in env["res.company"].sudo().search([]):
        record = Branding.get_for_company(company)
        record.write({
            "name": "Livraison Express",
            "favicon": icon_b64,
            "favicon_filename": "icon.svg",
            "login_logo": icon_b64,
            "login_logo_filename": "icon.svg",
            "app_logo": icon_b64,
            "app_logo_filename": "icon.svg",
        })
