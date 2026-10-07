from odoo import fields, models


class LikDriverLocation(models.Model):
    """M15 — livreur_locations table (LK-GEO-01). Append-only GPS trail."""

    _name = "likdelivery.driver.location"
    _description = "Position GPS livreur"
    _order = "id desc"

    livreur_id = fields.Many2one(
        "res.partner",
        required=True,
        index=True,
        domain="[('lik_role', '=', 'livreur')]",
    )
    latitude = fields.Float(required=True)
    longitude = fields.Float(required=True)
    accuracy = fields.Float()
    recorded_at = fields.Datetime(default=lambda self: fields.Datetime.now(), index=True)
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True
    )
