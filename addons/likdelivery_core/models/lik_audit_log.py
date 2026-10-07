from odoo import fields, models


class LikAuditLog(models.Model):
    """M16 — audit_logs table (LK-AUD-01/02)."""

    _name = "likdelivery.audit.log"
    _description = "Journal d'audit Livraison"
    _order = "id desc"

    actor_id = fields.Many2one("res.partner", index=True, ondelete="set null")
    actor_role = fields.Char()
    action = fields.Char(required=True, index=True)
    target_type = fields.Char()
    target_id = fields.Integer()
    ip = fields.Char()
    details = fields.Text()
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True
    )
