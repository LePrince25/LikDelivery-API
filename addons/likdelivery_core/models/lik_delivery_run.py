from odoo import fields, models

RUN_STATES = [
    ("CREATED", "Créée"),
    ("ACCEPTED", "Acceptée"),
    ("STARTED", "Démarrée"),
    ("PICKUP_INITIATED", "Récupération initiée"),
    ("PICKED_UP", "Colis récupéré"),
    ("IN_TRANSIT", "En transit"),
    ("DELIVERED", "Livrée"),
    ("CANCELLED", "Annulée"),
]

RUN_SOURCES = [
    ("boutique", "Boutique"),
    ("societe", "Société"),
    ("plateforme", "Plateforme"),
    ("admin", "Admin"),
]


class LikDeliveryRun(models.Model):
    """M9 — delivery_runs table: the driver-facing mission (LK-MSN-01).

    Distinct from the order: an order has at most one non-CANCELLED run
    (LK-ASN-03); the run carries its own price = the driver's earning
    (LK-PRC-04 variant).
    """

    _name = "likdelivery.delivery.run"
    _description = "Course / mission de livraison"
    _inherit = ["mail.thread"]
    _order = "id desc"

    order_id = fields.Many2one("likdelivery.order", index=True, ondelete="set null")
    standalone = fields.Boolean(default=False)
    pickup_address = fields.Text(required=True)
    pickup_lat = fields.Float()
    pickup_lon = fields.Float()
    dropoff_address = fields.Text(required=True)
    dropoff_lat = fields.Float()
    dropoff_lon = fields.Float()
    distance_km = fields.Float(default=0.0)
    price = fields.Float(default=0.0)
    state = fields.Selection(RUN_STATES, default="CREATED", tracking=True, index=True)
    livreur_id = fields.Many2one(
        "res.partner",
        index=True,
        domain="[('lik_role', '=', 'livreur')]",
        tracking=True,
    )
    source = fields.Selection(RUN_SOURCES, default="plateforme")
    otp_code = fields.Char(copy=False)
    qr_token = fields.Char(copy=False, index=True)
    is_fragile = fields.Boolean(default=False)
    pickup_time = fields.Datetime()
    delivery_time = fields.Datetime()
    rating = fields.Integer()
    rating_comment = fields.Text()
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True
    )
