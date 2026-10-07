from odoo import fields, models


class LikProductCategory(models.Model):
    """M2 — categories table."""

    _name = "likdelivery.product.category"
    _description = "Catégorie de produit Livraison"
    _order = "name"

    name = fields.Char(required=True)
    icon = fields.Char()


class LikProduct(models.Model):
    """M3 — supplier_products table.

    Deliberately NOT product.product (D4): keeps reference semantics and
    avoids sale/purchase/stock chain coupling.
    """

    _name = "likdelivery.product"
    _description = "Produit fournisseur Livraison"
    _order = "id desc"

    supplier_id = fields.Many2one(
        "res.partner",
        required=True,
        index=True,
        domain="[('lik_role', '=', 'fournisseur')]",
        string="Fournisseur",
    )
    category_id = fields.Many2one("likdelivery.product.category", string="Catégorie")
    name = fields.Char(required=True)
    description = fields.Text()
    price = fields.Float(default=0.0, required=True)
    stock = fields.Integer(default=0)
    active = fields.Boolean(default=True)
    fragile = fields.Boolean(default=False)
    # Reference stores an external URL string; uploaded files (LK-UPL-01)
    # additionally fill image_1920. Serializers prefer the uploaded image.
    lik_image_url = fields.Char(string="URL image externe")
    image_1920 = fields.Image("Image", max_width=1920, max_height=1920)
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True
    )
