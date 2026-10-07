from odoo import fields, models


class LikCartSession(models.Model):
    """M10 — cart_sessions table (LK-CRT-01).

    One row per (client|session_token, supplier, product); POST accumulates
    quantity, quantity <= 0 removes the row.
    """

    _name = "likdelivery.cart.session"
    _description = "Panier serveur Livraison"
    # Insertion order, as the reference (SQLite rowid order) — golden-master
    # responses depend on stable line ordering.
    _order = "id"

    client_id = fields.Many2one("res.partner", index=True)
    session_token = fields.Char(index=True, copy=False)
    supplier_id = fields.Many2one("res.partner", required=True, index=True)
    product_id = fields.Many2one("likdelivery.product", required=True)
    quantity = fields.Integer(default=1)
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True
    )
