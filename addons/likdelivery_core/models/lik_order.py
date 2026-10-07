from odoo import fields, models

from .lik_utils import generate_code, generate_otp

ORDER_STATES = [
    ("CREATED", "Créée"),
    ("PREPARING", "En préparation"),
    ("PICKUP_IN_PROGRESS", "Récupération en cours"),
    ("OUT_FOR_DELIVERY", "En cours de livraison"),
    ("DELIVERED", "Livrée"),
    ("CANCELLED", "Annulée"),
    ("FAILED", "Échouée"),
]

PAYMENT_METHODS = [
    ("cash_on_delivery", "Paiement à la livraison"),
    ("pay_at_pickup", "Paiement au retrait"),
    ("tmoney", "Tmoney"),
    ("flooz", "Flooz"),
    ("ecobank", "Ecobank Express"),
]

PAYMENT_STATUSES = [
    ("pending", "En attente"),
    ("paid", "Payé"),
    ("failed", "Échoué"),
]


class LikOrder(models.Model):
    """M7 — orders table (LK-ORD-01).

    Status strings are kept uppercase, identical to the reference, so
    golden-master comparisons match byte-for-byte.
    """

    _name = "likdelivery.order"
    _description = "Commande Livraison"
    _inherit = ["mail.thread"]
    _order = "id desc"
    _rec_name = "code"

    code = fields.Char(
        required=True, default=lambda self: generate_code("CMD-", 8), copy=False, index=True
    )
    client_id = fields.Many2one(
        "res.partner", index=True, domain="[('lik_role', '=', 'client')]", tracking=True
    )
    guest_phone = fields.Char()
    supplier_id = fields.Many2one(
        "res.partner",
        required=True,
        index=True,
        domain="[('lik_role', '=', 'fournisseur')]",
        tracking=True,
    )
    mode = fields.Selection(
        [("delivery", "Livraison"), ("pickup", "Retrait")],
        default="delivery",
        required=True,
    )
    state = fields.Selection(ORDER_STATES, default="CREATED", tracking=True, index=True)
    delivery_address = fields.Text()
    delivery_lat = fields.Float()
    delivery_lon = fields.Float()
    delivery_fee = fields.Float(default=0.0)
    product_total = fields.Float(default=0.0)
    total = fields.Float(default=0.0)
    payment_method = fields.Selection(
        PAYMENT_METHODS, default="cash_on_delivery", required=True
    )
    payment_status = fields.Selection(
        PAYMENT_STATUSES, default="pending", required=True, tracking=True
    )
    is_fragile = fields.Boolean(default=False)
    open_for_platform_claim = fields.Boolean(default=False)
    preferred_societe_id = fields.Many2one(
        "res.partner",
        domain="[('lik_role', '=', 'societe'), ('lik_validated_by_admin', '=', True)]",
    )
    supplier_wallet_credited = fields.Boolean(default=False, copy=False)
    otp_code = fields.Char(copy=False, default=lambda self: generate_otp())
    rating = fields.Integer()
    rating_comment = fields.Text()
    line_ids = fields.One2many("likdelivery.order.line", "order_id", string="Lignes")
    run_ids = fields.One2many("likdelivery.delivery.run", "order_id", string="Courses")
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True
    )

    _code_uniq = models.Constraint("unique(code)", "Code commande déjà utilisé.")


class LikOrderLine(models.Model):
    """M8 — order_lines table."""

    _name = "likdelivery.order.line"
    _description = "Ligne de commande Livraison"

    order_id = fields.Many2one(
        "likdelivery.order", required=True, ondelete="cascade", index=True
    )
    product_id = fields.Many2one("likdelivery.product", required=True)
    quantity = fields.Integer(default=1)
    unit_price = fields.Float(default=0.0)
    company_id = fields.Many2one(related="order_id.company_id", store=True, index=True)
