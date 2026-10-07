from odoo import fields, models

DAYS = [
    ("0", "Lundi"),
    ("1", "Mardi"),
    ("2", "Mercredi"),
    ("3", "Jeudi"),
    ("4", "Vendredi"),
    ("5", "Samedi"),
    ("6", "Dimanche"),
]


class LikOpeningHour(models.Model):
    """M4 — opening_hours table (LK-HRS-01).

    day_of_week: 0 = Monday (ISO, as reference). Times stored as float hours
    (6.5 = 06:30); services convert at the boundary. open == close means
    closed that day; overnight windows (22.0–6.0) are supported.
    """

    _name = "likdelivery.opening.hour"
    _description = "Plage horaire Livraison"
    _order = "partner_id, day_of_week, open_time"

    partner_id = fields.Many2one(
        "res.partner", required=True, ondelete="cascade", index=True
    )
    day_of_week = fields.Selection(DAYS, required=True)
    open_time = fields.Float(required=True, default=0.0)
    close_time = fields.Float(required=True, default=0.0)
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True
    )
