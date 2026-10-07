from odoo import fields, models

from .lik_utils import generate_code


class LikCourierRequest(models.Model):
    """M11 — courier_requests table.

    Reference is a stub (LK-SEC-10): creation + pricing only, no lifecycle
    endpoints. State selection intentionally minimal in v1.
    """

    _name = "likdelivery.courier.request"
    _description = "Course colis (hors catalogue)"
    _order = "id desc"
    _rec_name = "code"

    code = fields.Char(
        required=True, default=lambda self: generate_code("CRS-", 8), copy=False, index=True
    )
    client_id = fields.Many2one("res.partner", index=True)
    guest_phone = fields.Char()
    pickup_address = fields.Text(required=True)
    pickup_lat = fields.Float()
    pickup_lon = fields.Float()
    dropoff_address = fields.Text(required=True)
    dropoff_lat = fields.Float()
    dropoff_lon = fields.Float()
    distance_km = fields.Float(default=0.0)
    price = fields.Float(default=0.0)
    is_fragile = fields.Boolean(default=False)
    payment_method = fields.Selection(
        [
            ("cash_on_delivery", "Paiement à la livraison"),
            ("tmoney", "Tmoney"),
            ("flooz", "Flooz"),
            ("ecobank", "Ecobank Express"),
        ],
        default="cash_on_delivery",
        required=True,
    )
    payment_status = fields.Selection(
        [("pending", "En attente"), ("paid", "Payé"), ("failed", "Échoué")],
        default="pending",
        required=True,
    )
    state = fields.Selection([("CREATED", "Créée")], default="CREATED", index=True)
    livreur_id = fields.Many2one(
        "res.partner", index=True, domain="[('lik_role', '=', 'livreur')]"
    )
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True
    )

    _code_uniq = models.Constraint("unique(code)", "Code course déjà utilisé.")
