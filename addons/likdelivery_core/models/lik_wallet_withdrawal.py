from odoo import fields, models


class LikWalletWithdrawal(models.Model):
    """M17 — wallet_withdrawals table (LK-WAL-04).

    Reference creates withdrawals instantly with status=completed (no
    payout workflow); pending/cancelled exist in the enum.
    """

    _name = "likdelivery.wallet.withdrawal"
    _description = "Retrait portefeuille Livraison"
    _order = "id desc"

    user_id = fields.Many2one("res.partner", required=True, index=True)
    role = fields.Selection(
        [("fournisseur", "Fournisseur"), ("livreur", "Livreur")], required=True
    )
    amount = fields.Float(required=True)
    kind = fields.Selection(
        [
            ("product_sales", "Ventes produits"),
            ("delivery_fees", "Frais de livraison"),
        ],
        required=True,
    )
    state = fields.Selection(
        [("pending", "En attente"), ("completed", "Effectué"), ("cancelled", "Annulé")],
        default="completed",
        required=True,
        index=True,
    )
    note = fields.Char()
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True
    )
