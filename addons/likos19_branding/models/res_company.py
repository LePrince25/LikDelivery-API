from odoo import api, fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    likos_branding_ids = fields.One2many(
        "likos.branding",
        "company_id",
        string="LikOS branding",
    )
    likos_favicon = fields.Binary(
        related="likos_branding_ids.favicon",
        readonly=False,
        string="LikOS favicon",
    )
    likos_favicon_filename = fields.Char(
        related="likos_branding_ids.favicon_filename",
        readonly=False,
    )
    likos_login_logo = fields.Binary(
        related="likos_branding_ids.login_logo",
        readonly=False,
        string="LikOS login logo",
    )
    likos_login_logo_filename = fields.Char(
        related="likos_branding_ids.login_logo_filename",
        readonly=False,
    )
    likos_app_logo = fields.Binary(
        related="likos_branding_ids.app_logo",
        readonly=False,
        string="LikOS app logo",
    )
    likos_app_logo_filename = fields.Char(
        related="likos_branding_ids.app_logo_filename",
        readonly=False,
    )

    @api.model_create_multi
    def create(self, vals_list):
        companies = super().create(vals_list)
        if self.env.context.get("likos_skip_branding"):
            return companies
        companies._ensure_likos_branding()
        return companies

    def _ensure_likos_branding(self):
        Branding = self.env["likos.branding"].sudo()
        existing = set(Branding.search([("company_id", "in", self.ids)]).mapped("company_id").ids)
        for company in self:
            if company.id in existing:
                continue
            Branding.create({
                "name": company.name or "LikOS",
                "company_id": company.id,
            })
            existing.add(company.id)
