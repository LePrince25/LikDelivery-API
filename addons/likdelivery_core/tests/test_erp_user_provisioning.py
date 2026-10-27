"""res.users mirroring tests — platform accounts become connectable in Odoo.

Covers LikUser._lik_sync_erp_user(), the pbkdf2:sha256 login fallback
(ResUsers._check_credentials) and the D5/guest exclusions.
"""

from werkzeug.security import generate_password_hash

from odoo import exceptions
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "likdelivery")
class TestErpUserProvisioning(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.LikUser = cls.env["likdelivery.user"]
        cls.ResUsers = cls.env["res.users"].sudo()
        cls.group_client = cls.env.ref("likdelivery_core.group_lik_client")
        cls.group_fournisseur = cls.env.ref("likdelivery_core.group_lik_fournisseur")

    def _account(self, phone, role="client", **vals):
        return self.LikUser.create(
            {"name": f"Acc {phone}", "phone": phone, "lik_role": role, **vals}
        )

    def test_create_provisions_matching_partner(self):
        account = self._account("+22879100001")
        erp = account.lik_res_user_id
        self.assertTrue(erp)
        self.assertEqual(erp.partner_id, account.partner_id)
        self.assertEqual(erp.login, "+22879100001")
        self.assertIn(self.group_client, erp.group_ids)
        self.assertEqual(erp.lik_role_group_id, self.group_client)

    def test_role_change_reswaps_the_odoo_group(self):
        account = self._account("+22879100002")
        account.lik_role = "fournisseur"
        erp = account.lik_res_user_id
        self.assertIn(self.group_fournisseur, erp.group_ids)
        self.assertNotIn(self.group_client, erp.group_ids)
        self.assertEqual(erp.lik_role_group_id, self.group_fournisseur)

    def test_admin_role_and_guests_get_no_login(self):
        self.assertFalse(self._account("+22879100003", "admin").lik_res_user_id)
        self.assertFalse(
            self._account("+22879100004", "client", lik_is_guest=True).lik_res_user_id
        )

    def _stored_hash(self, user):
        """res.users.password is a computed field returning '' — the real hash
        is a DB column only read through SQL by the ORM."""
        self.env.cr.execute(
            "SELECT COALESCE(password, '') FROM res_users WHERE id=%s", (user.id,)
        )
        return self.env.cr.fetchone()[0]

    def test_set_password_reaches_both_stores(self):
        account = self._account("+22879100005")
        account.set_password("secret123")
        self.assertTrue(account.check_password("secret123"))
        erp = account.lik_res_user_id
        auth_info = erp.with_user(erp).sudo()._check_credentials(
            {"login": "+22879100005", "password": "secret123", "type": "password"},
            {"interactive": True},
        )
        self.assertEqual(auth_info["uid"], erp.id)

    def test_legacy_platform_hash_authenticates_then_upgrades(self):
        """Migrated/seeded accounts never exposed their clear password."""
        account = self._account("+22879100006")
        account.lik_password_hash = generate_password_hash(
            "legacy-pw", method="pbkdf2:sha256"
        )
        erp = account.lik_res_user_id
        self.assertTrue(erp.id)
        self.assertEqual(self._stored_hash(erp), "")
        auth_info = erp.with_user(erp).sudo()._check_credentials(
            {"login": "+22879100006", "password": "legacy-pw", "type": "password"},
            {"interactive": True},
        )
        self.assertEqual(auth_info["uid"], erp.id)
        # rehashed into Odoo's own scheme: the fallback is a one-time path
        self.assertTrue(self._stored_hash(erp).startswith("$pbkdf2-sha512$"))
        self.assertTrue(account.check_password("legacy-pw"))

    def test_wrong_password_is_denied(self):
        account = self._account("+22879100007")
        account.lik_password_hash = generate_password_hash(
            "right-pw", method="pbkdf2:sha256"
        )
        erp = account.lik_res_user_id
        with self.assertRaises(exceptions.AccessDenied):
            erp.with_user(erp).sudo()._check_credentials(
                {"login": "+22879100007", "password": "wrong-pw", "type": "password"},
                {"interactive": True},
            )

    def test_taken_odoo_login_skips_provisioning_without_failing(self):
        self.ResUsers.create({
            "name": "Staff existant",
            "login": "+22879100008",
            "group_ids": [(4, self.env.ref("base.group_user").id)],
        })
        account = self._account("+22879100008")
        self.assertTrue(account.exists())
        self.assertFalse(account.lik_res_user_id)

    def test_phone_less_account_stays_platform_only(self):
        """The SQLite ETL can carry rows without a phone: no login, no crash."""
        account = self.LikUser.create({"name": "Sans telephone", "lik_role": "livreur"})
        self.assertTrue(account.exists())
        self.assertFalse(account.lik_res_user_id)

    def test_archive_propagates_to_the_odoo_login(self):
        account = self._account("+22879100009")
        account.active = False
        self.assertFalse(account.lik_res_user_id.active)
        account.active = True
        self.assertTrue(account.lik_res_user_id.active)

    def test_sync_is_idempotent_and_backfills_orphans(self):
        account = self._account("+22879100010")
        erp = account.lik_res_user_id
        account.lik_res_user_id = False  # simulate a pre-mirroring account
        account.action_lik_sync_erp_user()
        self.assertEqual(account.lik_res_user_id, erp)
        self.assertEqual(
            self.ResUsers.search_count([("partner_id", "=", account.partner_id.id)]), 1
        )
