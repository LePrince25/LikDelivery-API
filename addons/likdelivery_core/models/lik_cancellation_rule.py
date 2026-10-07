from odoo import fields, models


class LikCancellationRule(models.Model):
    """M12 — cancellation_rules table (LK-CAN-02).

    Only penalty_percent of the first active rule is read by the reference;
    min/max hours and applies_to_* are dead fields — ported as-is.
    """

    _name = "likdelivery.cancellation.rule"
    _description = "Règle d'annulation"

    min_hours = fields.Integer(default=0)
    max_hours = fields.Integer()
    penalty_percent = fields.Float(default=80.0)
    applies_to_paid = fields.Boolean(default=True)
    applies_to_cash = fields.Boolean(default=True)
    active = fields.Boolean(default=True)
