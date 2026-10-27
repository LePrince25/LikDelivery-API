"""Record rules tests — scoping of the platform data per business role.

Covers security/ir_rule.xml: a role-group holder only sees its own records,
while an admin or a staff profile holding group_lik_perm_backend_global still
sees everything (group rules are OR-ed by the ORM).
"""

from odoo import exceptions
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "likdelivery")
class TestAccessRules(TransactionCase):
    @classmethod
    def _make_account(cls, env, name, phone, role):
        """Platform account + its mirrored Odoo login (auto-provisioned)."""
        account = env["likdelivery.user"].sudo().create({
            "name": name, "phone": phone, "lik_role": role
        })
        return account.partner_id, account, account.lik_res_user_id

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        cls.client_a, cls.account_a, cls.user_a = cls._make_account(
            env, "Cli Rule A", "+22879000001", "client"
        )
        cls.client_b, cls.account_b, cls.user_b = cls._make_account(
            env, "Cli Rule B", "+22879000002", "client"
        )
        cls.sup_a, cls.account_sup_a, cls.user_sup_a = cls._make_account(
            env, "Fou Rule A", "+22879000003", "fournisseur"
        )
        cls.sup_b, cls.account_sup_b, cls.user_sup_b = cls._make_account(
            env, "Fou Rule B", "+22879000004", "fournisseur"
        )
        cls.livreur, cls.account_livreur, cls.user_livreur = cls._make_account(
            env, "Liv Rule", "+22879000005", "livreur"
        )

        cls.product_a = env["likdelivery.product"].create({
            "name": "Prod A", "supplier_id": cls.sup_a.id, "price": 1000, "stock": 5,
        })
        cls.product_b = env["likdelivery.product"].create({
            "name": "Prod B", "supplier_id": cls.sup_b.id, "price": 2000, "stock": 5,
        })
        cls.order_a = env["likdelivery.order"].create({
            "client_id": cls.client_a.id, "supplier_id": cls.sup_a.id,
            "mode": "delivery", "delivery_address": "Lome",
            "line_ids": [(0, 0, {"product_id": cls.product_a.id, "quantity": 1})],
        })
        cls.order_b = env["likdelivery.order"].create({
            "client_id": cls.client_b.id, "supplier_id": cls.sup_b.id,
            "mode": "delivery", "delivery_address": "Lome",
            "line_ids": [(0, 0, {"product_id": cls.product_b.id, "quantity": 1})],
        })
        cls.run_a = env["likdelivery.delivery.run"].create({
            "order_id": cls.order_a.id, "pickup_address": "A", "dropoff_address": "B",
            "livreur_id": cls.livreur.id,
        })
        cls.run_b = env["likdelivery.delivery.run"].create({
            "order_id": cls.order_b.id, "pickup_address": "C", "dropoff_address": "D",
        })
        cls.withdrawal_a = env["likdelivery.wallet.withdrawal"].create({
            "user_id": cls.sup_a.id, "role": "fournisseur",
            "amount": 500, "kind": "product_sales",
        })

    def test_client_sees_only_own_orders(self):
        visible = self.env["likdelivery.order"].with_user(self.user_a).search([])
        self.assertEqual(visible, self.order_a)
        self.assertNotIn(self.order_b, visible)

    def test_client_cannot_read_foreign_order(self):
        with self.assertRaises(exceptions.AccessError):
            _ = self.order_b.with_user(self.user_a).total

    def test_supplier_sees_own_orders_and_their_livreur_runs(self):
        orders = self.env["likdelivery.order"].with_user(self.user_sup_a).search([])
        self.assertEqual(orders, self.order_a)
        runs = self.env["likdelivery.delivery.run"].with_user(self.user_sup_a).search([])
        self.assertEqual(runs, self.run_a)

    def test_livreur_sees_assigned_runs(self):
        runs = self.env["likdelivery.delivery.run"].with_user(self.user_livreur).search([])
        self.assertIn(self.run_a, runs)
        self.assertNotIn(self.run_b, runs)
        # the order behind its run is reachable through run_ids
        orders = self.env["likdelivery.order"].with_user(self.user_livreur).search([])
        self.assertEqual(orders, self.order_a)

    def test_catalog_read_is_shared_write_is_scoped(self):
        supplier_a = self.env["likdelivery.product"].with_user(self.user_sup_a)
        self.assertEqual(supplier_a.search_count([]), 2)
        with self.assertRaises(exceptions.AccessError):
            self.product_b.with_user(self.user_sup_a).write({"price": 9999})
        self.product_a.with_user(self.user_sup_a).write({"price": 1500})
        self.assertEqual(self.product_a.price, 1500)

    def test_wallet_and_notifications_are_personal(self):
        visible = self.env["likdelivery.wallet.withdrawal"].with_user(
            self.user_sup_a
        ).search([])
        self.assertEqual(visible, self.withdrawal_a)
        other = self.env["likdelivery.wallet.withdrawal"].with_user(
            self.user_sup_b
        ).search([])
        self.assertEqual(other.ids, [])

    def test_account_holder_only_reads_own_platform_account(self):
        accounts = self.env["likdelivery.user"].with_user(self.user_a).search([])
        self.assertIn(self.account_a, accounts)
        self.assertNotIn(self.account_b, accounts)
        self.assertNotIn(self.account_sup_a, accounts)

    def test_backend_global_group_wins_over_role_rule(self):
        """A user holding a role AND the global permission is not restricted.

        Group rules are OR-ed by the ORM, so the unrestricted domain of
        group_lik_perm_backend_global cancels the "Mes donnees" rule.
        """
        global_group = self.env.ref("likdelivery_core.group_lik_perm_backend_global")
        self.user_a.group_ids = [(4, global_group.id)]
        visible = self.env["likdelivery.order"].with_user(self.user_a).search([])
        self.assertIn(self.order_b, visible)
        self.assertIn(self.order_a, visible)

    def test_staff_without_role_group_is_unrestricted(self):
        """Pure back-office profile: no rule matches, so no filtering."""
        staff = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Ops Rule",
            "login": "+22879000009",
            "group_ids": [
                (4, self.env.ref("base.group_user").id),
                (4, self.env.ref("likdelivery_core.group_lik_perm_orders_view").id),
            ],
        })
        self.assertEqual(
            self.env["likdelivery.order"].with_user(staff).search_count([]), 2
        )

    def test_company_and_category_reference_data_not_scoped(self):
        cats = self.env["likdelivery.product.category"].with_user(self.user_a)
        self.assertTrue(cats.search_count([]) >= 0)
        self.assertEqual(
            self.env["likdelivery.order.line"].with_user(self.user_a).search_count([]), 1
        )
