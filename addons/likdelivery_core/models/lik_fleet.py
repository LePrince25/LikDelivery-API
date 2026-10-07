from odoo import fields, models


class LikShopDriver(models.Model):
    """M5 — supplier_livreurs: livreurs rattachés à une boutique (LK-SOC-07)."""

    _name = "likdelivery.shop.driver"
    _description = "Livreur de boutique"
    _order = "id desc"

    supplier_id = fields.Many2one(
        "res.partner",
        required=True,
        index=True,
        domain="[('lik_role', '=', 'fournisseur')]",
        string="Boutique",
    )
    livreur_id = fields.Many2one(
        "res.partner",
        required=True,
        index=True,
        domain="[('lik_role', '=', 'livreur')]",
        string="Livreur",
    )
    is_active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True
    )


class LikFleetDriver(models.Model):
    """M6 — societe_livreurs: flotte d'une société de livraison (LK-SOC-01).

    origin: internal = ressource propre de la société ;
            external = livreur pro indépendant rattaché.
    """

    _name = "likdelivery.fleet.driver"
    _description = "Livreur de flotte (société)"
    _order = "origin, id"

    societe_id = fields.Many2one(
        "res.partner",
        required=True,
        index=True,
        domain="[('lik_role', '=', 'societe')]",
        string="Société",
    )
    livreur_id = fields.Many2one(
        "res.partner",
        required=True,
        index=True,
        domain="[('lik_role', '=', 'livreur')]",
        string="Livreur",
    )
    origin = fields.Selection(
        [("internal", "Interne"), ("external", "Externe")],
        default="external",
        required=True,
    )
    is_active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True
    )
