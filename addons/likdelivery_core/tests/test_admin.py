"""Admin surface tests (S11+) — stats, analytics, wizards."""

from odoo.tests import TransactionCase, tagged

from ..services import admin_stats, checkout


@tagged("post_install", "-at_install", "likdelivery")
class TestAdminSurface(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env["res.partner"]
        partner = Partner.create({
            "name": "Cli ADM", "phone": "+22878000001", "lik_role": "client"
        })
        cls.client = cls.env["likdelivery.user"].create(
            {"name": "Cli ADM", "phone": "+22878000001", "partner_id": partner.id}
        )
        cls.shop_p = Partner.create({
            "name": "Shop ADM", "phone": "+22878000002", "lik_role": "fournisseur",
            "lik_validated_by_admin": True, "lik_company_name": "Shop ADM",
        })
        cls.product = cls.env["likdelivery.product"].create({
            "name": "P ADM", "supplier_id": cls.shop_p.id, "price": 2500,
            "stock": 10, "active": True,
        })

    def test_stats_keys_and_values(self):
        before = admin_stats.stats(self.env)
        checkout.create_legacy_order(
            self.env, self.client,
            {"supplier_id": self.shop_p.id, "mode": "pickup",
             "payment_method": "pay_at_pickup",
             "lines": [{"product_id": self.product.id, "quantity": 2}]},
        )
        after = admin_stats.stats(self.env)
        for key in ("users", "orders", "delivery_runs", "courier_requests",
                    "pending_validation", "today_orders", "total_revenue"):
            self.assertIn(key, after)
        self.assertEqual(after["orders"], before["orders"] + 1)
        self.assertEqual(after["today_orders"], before["today_orders"] + 1)
        # quirk LK-SEC-09: revenue includes non-delivered orders
        self.assertEqual(after["total_revenue"], before["total_revenue"] + 5000.0)

    def test_analytics(self):
        checkout.create_legacy_order(
            self.env, self.client,
            {"supplier_id": self.shop_p.id, "mode": "pickup",
             "payment_method": "pay_at_pickup",
             "lines": [{"product_id": self.product.id, "quantity": 1}]},
        )
        result = admin_stats.analytics(self.env)
        self.assertIn("orders_by_day", result)
        self.assertIn("status_counts", result)
        self.assertIn("top_suppliers", result)
        self.assertTrue(result["orders_by_day"])
        self.assertIn("CREATED", result["status_counts"])
        self.assertLessEqual(len(result["top_suppliers"]), 5)

    def test_notification_test_wizard(self):
        wiz = self.env["likdelivery.notification.test"].create({
            "lik_user_id": self.client.id, "title": "T", "body": "B",
        })
        wiz.action_send()
        notif = self.env["likdelivery.notification"].search(
            [("user_id", "=", self.client.partner_id.id), ("title", "=", "T")]
        )
        self.assertEqual(len(notif), 1)

    def test_assign_driver_wizard(self):
        liv = self.env["res.partner"].create({
            "name": "Liv ADM", "phone": "+22878000003", "lik_role": "livreur",
        })
        result = checkout.create_legacy_order(
            self.env, self.client,
            {"supplier_id": self.shop_p.id, "mode": "delivery",
             "payment_method": "cash_on_delivery", "delivery_address": "Lome",
             "delivery_lat": 6.16, "delivery_lon": 1.21,
             "lines": [{"product_id": self.product.id, "quantity": 1}]},
        )
        order = self.env["likdelivery.order"].browse(result["order_id"])
        wiz = self.env["likdelivery.assign.driver"].create({
            "order_id": order.id, "livreur_id": liv.id,
        })
        wiz.action_assign()
        run = order.run_ids.filtered(lambda r: r.state != "CANCELLED")[:1]
        self.assertEqual(run.livreur_id, liv)
        self.assertEqual(order.state, "OUT_FOR_DELIVERY")
