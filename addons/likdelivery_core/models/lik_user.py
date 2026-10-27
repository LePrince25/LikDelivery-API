import logging

from werkzeug.security import check_password_hash, generate_password_hash

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Command

LIK_ROLES = [
    ("client", "Client"),
    ("fournisseur", "Fournisseur"),
    ("livreur", "Livreur"),
    ("societe", "Société de livraison"),
    ("admin", "Administrateur"),
]

_logger = logging.getLogger(__name__)

# Roles that never get an Odoo login: `admin` is API-only by design (D5, the
# back-office account is seeded separately) and guests have no credentials.
NO_ERP_LOGIN_ROLES = ("admin",)


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
    lik_res_user_id = fields.Many2one(
        "res.users",
        string="Compte Odoo",
        ondelete="set null",
        index=True,
        copy=False,
        help="Compte de connexion Odoo miroir du compte plateforme. Vide pour "
        "le role admin (D5), les comptes invites et quand le numero est deja "
        "pris comme identifiant Odoo.",
    )

    def set_password(self, password):
        self.ensure_one()
        self.lik_password_hash = generate_password_hash(
            password, method="pbkdf2:sha256"
        )
        # Odoo hashes with pbkdf2_sha512 only: the two stores cannot share a
        # hash, so the clear password (available at signup) fills both.
        self._lik_sync_erp_user(password=password)

    def check_password(self, password):
        self.ensure_one()
        if not self.lik_password_hash:
            return False
        return check_password_hash(self.lik_password_hash, password)

    @api.model_create_multi
    def create(self, vals_list):
        accounts = super().create(vals_list)
        accounts._lik_sync_erp_user()
        return accounts

    def write(self, vals):
        # res.partner refuses to archive a contact still linked to an active
        # login, so the Odoo account has to be archived before the delegation.
        if "active" in vals and not vals["active"]:
            self.sudo().lik_res_user_id.with_context(mail_notrack=True).write(
                {"active": False}
            )
        res = super().write(vals)
        if vals.keys() & {"phone", "active", "lik_role", "lik_is_guest"}:
            self._lik_sync_erp_user()
        return res

    def _lik_erp_role_group(self):
        """Odoo group matching the platform role, None when no login is allowed."""
        self.ensure_one()
        if self.lik_is_guest or self.lik_role in NO_ERP_LOGIN_ROLES:
            return self.env["res.groups"].browse()
        return self.env["res.groups"].sudo().search(
            [("lik_is_role_group", "=", True), ("lik_role_code", "=", self.lik_role)],
            limit=1,
        )

    def _lik_sync_erp_user(self, password=None):
        """Mirror each platform account into a connectable res.users.

        Both accounts share one res.partner (Odoo's native "one contact, one
        login" layout), so the identity, the KYC documents and the wallet stay
        single-sourced. A login already held by another contact is skipped with
        a warning instead of breaking the signup flow.
        """
        ResUsers = self.env["res.users"].sudo().with_context(
            mail_create_nolog=True,
            mail_notrack=True,
            # auth_signup would otherwise mail a "set your password" link on
            # every signup, pointing at a platform account that already has one.
            no_reset_password=True,
        )
        role_groups = self.env["res.groups"].sudo().search(
            [("lik_is_role_group", "=", True)]
        )
        for account in self.sudo():
            group = account._lik_erp_role_group()
            partner = account.partner_id
            if not group:
                if account.lik_res_user_id:
                    account.lik_res_user_id = False
                continue

            erp_user = account.lik_res_user_id or ResUsers.search(
                [("partner_id", "=", partner.id)], limit=1
            )
            if not erp_user:
                # res.users.login is required and UNIQUE; the SQLite ETL can
                # carry phone-less rows, which simply stay platform-only.
                if not account.phone:
                    continue
                if ResUsers.search_count([("login", "=", account.phone)]):
                    _logger.warning(
                        "Compte plateforme %s: l'identifiant Odoo %s est deja pris, "
                        "connexion Odoo non provisionnee.",
                        account.id,
                        account.phone,
                    )
                    continue
                erp_user = ResUsers.create({
                    "name": partner.name or account.phone,
                    "login": account.phone,
                    "partner_id": partner.id,
                    "active": account.active,
                    "group_ids": [Command.link(group.id)],
                })
            else:
                vals = {"active": account.active}
                if (
                    account.phone
                    and erp_user.login != account.phone
                    and not ResUsers.search_count(
                        [("login", "=", account.phone), ("id", "!=", erp_user.id)]
                    )
                ):
                    vals["login"] = account.phone
                vals["group_ids"] = [
                    Command.unlink(other.id)
                    for other in erp_user.group_ids & role_groups
                    if other != group
                ] + [Command.link(group.id)]
                erp_user.write(vals)

            if account.lik_res_user_id != erp_user:
                account.lik_res_user_id = erp_user.id
            if password:
                erp_user.password = password

    def action_lik_sync_erp_user(self):
        """Back-office remedy for accounts provisioned before their phone or
        role was usable: re-run the mirroring and report what changed. The
        bound server action has no group field of its own in Odoo 19, so the
        guard lives here."""
        self._check_lik_permission("likdelivery_core.group_lik_perm_network_manage")
        before = {account.id: account.lik_res_user_id.id for account in self}
        self._lik_sync_erp_user()
        created = sum(
            1
            for account in self
            if account.lik_res_user_id.id and not before[account.id]
        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "message": _(
                    "%(created)s compte(s) Odoo cree(s) sur %(total)s.",
                    created=created,
                    total=len(self),
                ),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def _check_lik_permission(self, group_xmlid):
        if not self.env.user.has_group(group_xmlid):
            raise AccessError(
                _("Vous n'avez pas la permission requise pour cette action.")
            )

    def action_validate_account(self):
        """LK-KYC-02 — back-office validation (group_lik_perm_kyc_manage)."""
        from ..services.notification import notify
        from ..services.audit import audit_row

        self._check_lik_permission("likdelivery_core.group_lik_perm_kyc_manage")
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
        reference GET /api/admin/users/<id>/kyc endpoint. Gated by
        group_lik_perm_kyc_manage."""
        from ..services.audit import audit_row

        self.ensure_one()
        self._check_lik_permission("likdelivery_core.group_lik_perm_kyc_manage")
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
