"""Profile + admin validation tests (S11) — LK-AUT-05..09, LK-KYC-02."""

from odoo.tests import TransactionCase, tagged

from ..services import profile


@tagged("post_install", "-at_install", "likdelivery")
class TestProfile(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env["res.partner"]

        def mkuser(name, phone, role, **kw):
            first, _, last = name.partition(" ")
            partner = Partner.create(
                dict(name=name, phone=phone, lik_role=role,
                     lik_first_name=first, lik_last_name=last or None, **kw)
            )
            user = cls.env["likdelivery.user"].create(
                {"name": name, "phone": phone, "partner_id": partner.id}
            )
            user.set_password("pass123")
            return user

        cls.client = mkuser("Cli S11", "+22877000001", "client")
        cls.client2 = mkuser("Cli S11b", "+22877000002", "client")
        cls.livreur = mkuser("Liv S11", "+22877000003", "livreur")
        cls.fournisseur = mkuser("Fou S11", "+22877000004", "fournisseur")
        cls.admin = mkuser("Admin S11", "+22877000005", "admin")
        cls.soc = Partner.create({
            "name": "Soc S11", "phone": "+22877000006", "lik_role": "societe",
            "lik_validated_by_admin": True,
        })
        cls.soc_pending = Partner.create({
            "name": "Soc S11b", "phone": "+22877000007", "lik_role": "societe",
            "lik_validated_by_admin": False,
        })

    def test_profile_get_client(self):
        payload = profile.profile_payload(self.env, self.client)
        self.assertEqual(payload["phone"], "+22877000001")
        self.assertEqual(payload["role"], "client")
        self.assertNotIn("wallet", payload)

    def test_profile_livreur_extras_and_self_heal(self):
        # fake a delivered run directly
        run = self.env["likdelivery.delivery.run"].create({
            "pickup_address": "A", "dropoff_address": "B", "price": 700,
            "state": "DELIVERED", "livreur_id": self.livreur.partner_id.id,
        })
        self.livreur.partner_id.lik_total_deliveries = 0
        payload = profile.profile_payload(self.env, self.livreur)
        self.assertEqual(payload["total_deliveries"], 1)  # self-healed
        self.assertEqual(payload["stats"]["delivered_count"], 1)
        self.assertEqual(payload["stats"]["total_earnings"], 700.0)
        self.assertEqual(payload["wallet"]["available"], 700.0)
        self.assertEqual(payload["full_name"], "Liv S11")

    def test_profile_fournisseur_wallet(self):
        payload = profile.profile_payload(self.env, self.fournisseur)
        self.assertIn("wallet", payload)
        self.assertEqual(payload["wallet"]["kind"], "product_sales")

    def test_update_fields_and_company_strip(self):
        result = profile.update_profile(
            self.env, self.client,
            {"first_name": "Ama", "last_name": "Test", "address": "  Lomé  "},
        )
        self.assertEqual(result["first_name"], "Ama")
        self.assertEqual(self.client.partner_id.street, "  Lomé  ")  # not stripped
        result = profile.update_profile(
            self.env, self.fournisseur, {"company_name": "   "}
        )
        self.assertFalse(self.fournisseur.partner_id.lik_company_name)

    def test_phone_validation(self):
        with self.assertRaises(ValueError):
            profile.update_profile(self.env, self.client, {"phone": ""})
        with self.assertRaises(ValueError):
            profile.update_profile(self.env, self.client, {"phone": "12"})
        with self.assertRaises(ValueError):
            profile.update_profile(self.env, self.client, {"phone": "++22812345678"})
        with self.assertRaises(ValueError):  # taken by client2
            profile.update_profile(self.env, self.client, {"phone": "+22877000002"})
        result = profile.update_profile(
            self.env, self.client, {"phone": "+228 77 00 00 09"}
        )
        self.assertEqual(result["phone"], "+22877000009")  # spaces stripped

    def test_password_change_rules(self):
        with self.assertRaises(ValueError) as ctx:
            profile.update_profile(
                self.env, self.client,
                {"current_password": "wrong", "new_password": "newpass1"},
            )
        self.assertIn("actuel incorrect", str(ctx.exception))
        with self.assertRaises(ValueError):
            profile.update_profile(
                self.env, self.client,
                {"current_password": "pass123", "new_password": "abc"},
            )
        with self.assertRaises(ValueError):
            profile.update_profile(
                self.env, self.client,
                {"current_password": "pass123", "new_password": "newpass1",
                 "new_password_confirm": "different"},
            )
        with self.assertRaises(ValueError):
            profile.update_profile(
                self.env, self.client,
                {"current_password": "pass123", "new_password": "pass123"},
            )
        profile.update_profile(
            self.env, self.client,
            {"current_password": "pass123", "new_password": "newpass1"},
        )
        self.assertTrue(self.client.check_password("newpass1"))

    def test_preferred_societe(self):
        result = profile.update_profile(
            self.env, self.client, {"preferred_societe_id": self.soc.id}
        )
        self.assertEqual(result["preferred_societe_id"], self.soc.id)
        with self.assertRaises(ValueError):
            profile.update_profile(
                self.env, self.client, {"preferred_societe_id": self.soc_pending.id}
            )
        # clear with empty
        result = profile.update_profile(
            self.env, self.client, {"preferred_societe_id": ""}
        )
        self.assertIsNone(result["preferred_societe_id"])
        # non-client: silently ignored (reference behavior)
        profile.update_profile(
            self.env, self.fournisseur, {"preferred_societe_id": self.soc.id}
        )
        self.assertFalse(self.fournisseur.partner_id.lik_preferred_societe_id)

    def test_admin_validate_account(self):
        target = self.env["res.partner"].create({
            "name": "Pending S11", "phone": "+22877000008", "lik_role": "fournisseur",
            "lik_validated_by_admin": False,
        })
        profile.validate_account(self.env, self.admin, target)
        self.assertTrue(target.lik_validated_by_admin)
        notif = self.env["likdelivery.notification"].search(
            [("user_id", "=", target.id)], order="id desc", limit=1
        )
        self.assertEqual(notif.title, "Compte valide")
        audit = self.env["likdelivery.audit.log"].search(
            [("action", "=", "VALIDATE_USER")], order="id desc", limit=1
        )
        self.assertEqual(audit.target_id, target.id)
        with self.assertRaises(PermissionError):
            profile.validate_account(self.env, self.client, target)
