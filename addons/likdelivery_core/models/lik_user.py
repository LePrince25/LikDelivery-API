from werkzeug.security import check_password_hash, generate_password_hash

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

LIK_ROLES = [
    ("client", "Client"),
    ("fournisseur", "Fournisseur"),
    ("livreur", "Livreur"),
    ("societe", "Société de livraison"),
    ("admin", "Administrateur"),
]


class ResPartner(models.Model):
    """Single-table multi-role user hub (M1).

    Mirrors Flask `users`: one partner per platform account, role-specific
    fields on the same record. Login identifier = `phone`.
    """

    _inherit = "res.partner"

    lik_role = fields.Selection(
        LIK_ROLES, string="Rôle Livraison", default="client", index=True
    )
    lik_first_name = fields.Char(string="Prénom")
    lik_last_name = fields.Char(string="Nom")
    # Reference `company_name` (fournisseurs/sociétés). Distinct from the
    # native res.partner company fields on purpose.
    lik_company_name = fields.Char(string="Société / Boutique")
    lik_validated_by_admin = fields.Boolean(default=False)
    # KYC documents (LK-KYC-01): binary + filename, group-protected in views.
    lik_id_document = fields.Binary(attachment=True)
    lik_id_document_filename = fields.Char()
    lik_cfe_document = fields.Binary(attachment=True)
    lik_cfe_document_filename = fields.Char()
    # Livreur fields
    lik_vehicle_type = fields.Char(string="Type de véhicule")
    lik_license_plate = fields.Char(string="Plaque d'immatriculation")
    lik_average_rating = fields.Float(default=5.0)
    lik_total_deliveries = fields.Integer(default=0)
    # Client: preferred delivery company (LK-AUT-08)
    lik_preferred_societe_id = fields.Many2one(
        "res.partner",
        string="Société préférée",
        domain="[('lik_role', '=', 'societe'), ('lik_validated_by_admin', '=', True)]",
    )
    # Livreur interne possédé par une société (None = livreur externe / indépendant)
    lik_employer_societe_id = fields.Many2one(
        "res.partner",
        string="Société employeur",
        domain="[('lik_role', '=', 'societe')]",
    )
    lik_user_id = fields.One2many(
        "likdelivery.user", "partner_id", string="Compte plateforme"
    )
    # Wallet — derived, never stored (D6, LK-WAL-03)
    lik_wallet_earned = fields.Float(compute="_compute_lik_wallet")
    lik_wallet_withdrawn = fields.Float(compute="_compute_lik_wallet")
    lik_wallet_available = fields.Float(compute="_compute_lik_wallet")

    def _compute_lik_wallet(self):
        Run = self.env["likdelivery.delivery.run"].sudo()
        Order = self.env["likdelivery.order"].sudo()
        Withdrawal = self.env["likdelivery.wallet.withdrawal"].sudo()
        for partner in self:
            earned = 0.0
            if partner.lik_role == "livreur":
                runs = Run.search(
                    [("livreur_id", "=", partner.id), ("state", "=", "DELIVERED")]
                )
                earned = sum(runs.mapped("price"))
            elif partner.lik_role == "fournisseur":
                orders = Order.search(
                    [("supplier_id", "=", partner.id), ("state", "=", "DELIVERED")]
                )
                earned = sum(orders.mapped("product_total"))
            withdrawn = sum(
                Withdrawal.search(
                    [
                        ("user_id", "=", partner.id),
                        ("state", "in", ["completed", "pending"]),
                    ]
                ).mapped("amount")
            )
            partner.lik_wallet_earned = earned
            partner.lik_wallet_withdrawn = withdrawn
            partner.lik_wallet_available = max(0.0, round(earned - withdrawn, 0))


class LikUser(models.Model):
    """Platform account (M1). Holds credentials; identity lives on the partner.

    `_inherits` res.partner: all lik_* identity fields are readable directly
    on this model. Passwords stay pbkdf2:sha256 (LK-AUT-05) so migrated
    hashes keep working.
    """

    _name = "likdelivery.user"
    _description = "Compte plateforme Livraison"
    _inherits = {"res.partner": "partner_id"}
    _rec_name = "phone"

    partner_id = fields.Many2one(
        "res.partner", required=True, ondelete="cascade"
    )
    lik_password_hash = fields.Char(string="Hash mot de passe", copy=False)
    lik_jwt_jti = fields.Char(string="JWT jti courant", copy=False)
    lik_is_guest = fields.Boolean(default=False)

    def set_password(self, password):
        self.ensure_one()
        self.lik_password_hash = generate_password_hash(
            password, method="pbkdf2:sha256"
        )

    def check_password(self, password):
        self.ensure_one()
        if not self.lik_password_hash:
            return False
        return check_password_hash(self.lik_password_hash, password)

    def action_validate_account(self):
        """LK-KYC-02 — back-office validation button (group_lik_admin)."""
        from ..services.notification import notify
        from ..services.audit import audit_row

        for user in self:
            user.partner_id.lik_validated_by_admin = True
            notify(
                self.env,
                partner=user.partner_id,
                title="Compte valide",
                body="Votre compte a ete valide par l'administration.",
            )
            audit_row(
                self.env,
                {"id": self.env.user.partner_id.id, "role": "admin"},
                "VALIDATE_USER",
                "User",
                user.id,
            )

    def action_view_kyc(self):
        """Admin KYC consultation — logs VIEW_KYC (LK-AUD-02) like the
        reference GET /api/admin/users/<id>/kyc endpoint."""
        from ..services.audit import audit_row

        self.ensure_one()
        audit_row(
            self.env,
            {"id": self.env.user.partner_id.id, "role": "admin"},
            "VIEW_KYC",
            "User",
            self.id,
        )
        return True

    @api.constrains("phone")
    def _check_phone_unique(self):
        for user in self:
            if user.phone:
                duplicate = self.search_count(
                    [("phone", "=", user.phone), ("id", "!=", user.id)]
                )
                if duplicate:
                    raise ValidationError(
                        _("Ce numéro de téléphone est déjà utilisé.")
                    )
