from odoo import fields, models


class LikIdempotencyKey(models.Model):
    """Stored Idempotency-Key responses (24 h TTL, lazy expiry)."""

    _name = "likdelivery.idempotency.key"
    _description = "Clé d'idempotence API"
    _order = "id desc"

    key = fields.Char(required=True, index=True)
    lik_user_id = fields.Many2one("likdelivery.user", index=True, ondelete="cascade")
    endpoint = fields.Char(required=True)
    status = fields.Integer(default=200)
    response_body = fields.Text()
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True
    )

    _key_endpoint_uniq = models.Constraint(
        "unique(key, lik_user_id, endpoint)",
        "Clé d'idempotence déjà utilisée pour cet endpoint.",
    )
