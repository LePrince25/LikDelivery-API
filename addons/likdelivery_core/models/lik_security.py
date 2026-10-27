from odoo import _, api, fields, models
from odoo.exceptions import AccessDenied, ValidationError

from .lik_user import LIK_ROLES


class ResGroups(models.Model):
    """Technical markers used to tell role groups and permission groups apart.

    A role group is a high-level profile (client, livreur, fournisseur,
    société, admin). Its ``implied_ids`` carry every permission of the role.
    A permission group is a granular capability that can be granted on top
    of the role from the user form.
    """

    _inherit = "res.groups"

    lik_is_role_group = fields.Boolean(
        string="Groupe de rôle LikDelivery", default=False, copy=False
    )
    lik_is_permission_group = fields.Boolean(
        string="Permission LikDelivery", default=False, copy=False
    )
    lik_role_code = fields.Selection(
        LIK_ROLES,
        string="Code rôle",
        copy=False,
        help="Rôle plateforme synchronisé sur le contact de l'utilisateur.",
    )
    lik_description = fields.Text(string="Description", translate=True)
    lik_sequence = fields.Integer(string="Séquence LikDelivery", default=100)


class ResUsers(models.Model):
    _inherit = "res.users"

    # Role and permissions are both derived from group_ids, which stays the
    # single source of truth (standard Odoo group widget included).
    lik_role_group_id = fields.Many2one(
        "res.groups",
        string="Groupe de rôle",
        domain=[("lik_is_role_group", "=", True)],
        compute="_compute_lik_role_group_id",
        inverse="_inverse_lik_role_group_id",
        help="Le rôle accorde automatiquement toutes ses permissions.",
    )
    lik_role_permission_ids = fields.Many2many(
        "res.groups",
        string="Permissions du rôle",
        compute="_compute_lik_role_permission_ids",
        compute_sudo=True,
    )
    lik_extra_permission_ids = fields.Many2many(
        "res.groups",
        string="Permissions supplémentaires",
        domain=[("lik_is_permission_group", "=", True)],
        compute="_compute_lik_extra_permission_ids",
        inverse="_inverse_lik_extra_permission_ids",
        compute_sudo=True,
        help="Permissions ajoutées en plus de celles du rôle.",
    )
    lik_effective_permission_ids = fields.Many2many(
        "res.groups",
        string="Permissions effectives",
        compute="_compute_lik_effective_permission_ids",
        compute_sudo=True,
    )

    @api.model
    def _lik_role_groups(self):
        return self.env["res.groups"].sudo().search(
            [("lik_is_role_group", "=", True)], order="lik_sequence, id"
        )

    def _check_credentials(self, credential, env):
        """Allow an Odoo login with the platform (pbkdf2:sha256) password.

        Signup and the SQLite ETL store a werkzeug hash Odoo's crypt context
        (pbkdf2_sha512 only) cannot verify. The platform hash is tried after the
        native check failed, never instead of it, and a success is rehashed into
        Odoo's own scheme so the fallback runs at most once per account.
        """
        try:
            return super()._check_credentials(credential, env)
        except AccessDenied:
            if credential.get("type") != "password" or not credential.get("password"):
                raise
            account = self.env["likdelivery.user"].sudo().search(
                [("partner_id", "=", self.partner_id.id), ("active", "=", True)],
                limit=1,
            )
            if not account or not account.check_password(credential["password"]):
                raise
            self.sudo().password = credential["password"]
            return {
                "uid": self.env.user.id,
                "auth_method": "password",
                "mfa": "default",
            }

    @api.model
    def _lik_permission_groups(self):
        return self.env["res.groups"].sudo().search(
            [("lik_is_permission_group", "=", True)], order="lik_sequence, id"
        )

    @api.depends("group_ids")
    def _compute_lik_role_group_id(self):
        role_groups = self._lik_role_groups()
        for user in self:
            roles = user.group_ids & role_groups
            user.lik_role_group_id = roles[:1] or False

    @api.constrains("group_ids")
    def _check_lik_single_role(self):
        for user in self:
            if len(user.group_ids.filtered("lik_is_role_group")) > 1:
                raise ValidationError(
                    _("Un utilisateur ne peut avoir qu'un seul rôle Livraison.")
                )

    def _inverse_lik_role_group_id(self):
        role_groups = self._lik_role_groups()
        for user in self:
            role = user.lik_role_group_id
            if role and not role.lik_is_role_group:
                raise ValidationError(
                    _("Le groupe sélectionné n'est pas un groupe de rôle LikDelivery.")
                )
            user.group_ids = (user.group_ids - role_groups) | role
            if role and role.lik_role_code and user.partner_id:
                user.partner_id.lik_role = role.lik_role_code

    @api.depends("group_ids", "group_ids.all_implied_ids")
    def _compute_lik_role_permission_ids(self):
        permission_groups = self._lik_permission_groups()
        for user in self:
            role = user.lik_role_group_id
            user.lik_role_permission_ids = (
                role.all_implied_ids & permission_groups
                if role
                else permission_groups.browse()
            )

    @api.depends("group_ids", "group_ids.all_implied_ids")
    def _compute_lik_extra_permission_ids(self):
        permission_groups = self._lik_permission_groups()
        for user in self:
            role = user.lik_role_group_id
            role_permissions = (
                role.all_implied_ids & permission_groups
                if role
                else permission_groups.browse()
            )
            explicit = user.group_ids & permission_groups
            user.lik_extra_permission_ids = explicit - role_permissions

    def _inverse_lik_extra_permission_ids(self):
        permission_groups = self._lik_permission_groups()
        for user in self:
            extras = user.lik_extra_permission_ids
            if any(not group.lik_is_permission_group for group in extras):
                raise ValidationError(
                    _(
                        "Une des permissions sélectionnées n'est pas une permission "
                        "LikDelivery."
                    )
                )
            user.group_ids = (user.group_ids - permission_groups) | extras

    @api.depends("group_ids", "group_ids.all_implied_ids")
    def _compute_lik_effective_permission_ids(self):
        permission_groups = self._lik_permission_groups()
        for user in self:
            role = user.lik_role_group_id
            role_permissions = (
                role.all_implied_ids & permission_groups
                if role
                else permission_groups.browse()
            )
            explicit = user.group_ids & permission_groups
            user.lik_effective_permission_ids = role_permissions | explicit

    @api.onchange("lik_role_group_id")
    def _onchange_lik_role_group_id(self):
        """Refresh the standard group widget as soon as the role changes."""
        role_groups = self._lik_role_groups()
        if self.lik_role_group_id:
            self.group_ids = (self.group_ids - role_groups) | self.lik_role_group_id
