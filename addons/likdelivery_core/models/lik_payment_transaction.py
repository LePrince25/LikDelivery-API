from odoo import fields, models

from .lik_utils import generate_code

PROVIDERS = [
    ("tmoney", "Tmoney"),
    ("flooz", "Flooz"),
    ("ecobank", "Ecobank Express"),
    ("cash_on_delivery", "Paiement à la livraison"),
    ("pay_at_pickup", "Paiement au retrait"),
    ("refund", "Remboursement"),
    ("cash", "Espèces"),
]

TX_STATES = [
    ("pending", "En attente"),
    ("success", "Succès"),
    ("failed", "Échoué"),
    ("refunded", "Remboursé"),
]


class LikPaymentTransaction(models.Model):
    """M13 — payment_transactions table (LK-PAY-01/02).

    Reference polymorphism (target_type + target_id) is mapped to two
    concrete many2ones; exactly one is set, mirroring target_type.
    """

    _name = "likdelivery.payment.transaction"
    _description = "Transaction de paiement Livraison"
    _order = "id desc"
    _rec_name = "reference"

    reference = fields.Char(
        required=True,
        default=lambda self: generate_code("PAY-", 10),
        copy=False,
        index=True,
    )
    target_type = fields.Selection(
        [("order", "Commande"), ("courier", "Course colis")], required=True
    )
    order_id = fields.Many2one("likdelivery.order", index=True)
    courier_request_id = fields.Many2one("likdelivery.courier.request", index=True)
    amount = fields.Float(required=True)
    provider = fields.Selection(PROVIDERS, required=True)
    phone = fields.Char()
    state = fields.Selection(TX_STATES, default="pending", required=True, index=True)
    provider_ref = fields.Char(copy=False)
    failure_reason = fields.Char()
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True
    )

    _reference_uniq = models.Constraint(
        "unique(reference)", "Référence de paiement déjà utilisée."
    )
