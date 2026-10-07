"""Wallet / cancellation / rating tests (S9) — LK-WAL-03/04, LK-CAN-01..04,
LK-RAT-01/02."""

from odoo.tests import TransactionCase, tagged

from ..services import (
    assignment,
    cancellation,
    checkout,
    mission_lifecycle,
    order_lifecycle,
    rating,
    wallet,
)


@tagged("post_install", "-at_install", "likdelivery")
class TestWalletCancellationRating(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env["res.partner"]

        def mkuser(name, phone, role, **kw):
            partner = Partner.create(dict(name=name, phone=phone, lik_role=role, **kw))
            return cls.env["likdelivery.user"].create(
                {"name": name, "phone": phone, "partner_id": partner.id}
            )

        cls.client = mkuser("Cli S9", "+22875000001", "client")
        cls.client2 = mkuser("Cli S9b", "+22875000002", "client")
        cls.shop = mkuser(
            "Shop S9", "+22875000003", "fournisseur",
            lik_validated_by_admin=True, lik_company_name="Shop S9",
            partner_latitude=6.1725, partner_longitude=1.2253,
        )
        cls.livreur = mkuser("Liv S9", "+22875000004", "livreur")
        cls.admin = mkuser("Admin S9", "+22875000005", "admin")
        cls.product = cls.env["likdelivery.product"].create({
            "name": "P S9", "supplier_id": cls.shop.partner_id.id,
            "price": 5000, "stock": 50, "active": True,
        })

    def _delivered_order(self, payment="cash_on_delivery", qty=2):
        data = {
            "supplier_id": self.shop.partner_id.id, "mode": "delivery",
            "payment_method": payment, "delivery_address": "Lome",
            "delivery_lat": 6.16, "delivery_lon": 1.21,
            "lines": [{"product_id": self.product.id, "quantity": qty}],
        }
        result = checkout.create_legacy_order(self.env, self.client, data)
        order = self.env["likdelivery.order"].browse(result["order_id"])
        if payment not in ("cash_on_delivery", "pay_at_pickup"):
            order.payment_status = "paid"
        run = assignment.assign_livreur_to_order(
            self.env, order, self.livreur.partner_id, self.admin
        )
        for st in ("STARTED", "PICKED_UP", "IN_TRANSIT"):
            mission_lifecycle.apply_mission_status(self.env, run, st, self.livreur)
        if payment == "cash_on_delivery":
            mission_lifecycle.confirm_cod_payment(self.env, self.livreur, run)
        mission_lifecycle.apply_mission_status(
            self.env, run, "DELIVERED", self.livreur, otp=run.otp_code
        )
        return order, run

    # ---------- wallet ----------
    def test_wallet_snapshot_livreur(self):
        order, run = self._delivered_order()
        snap = wallet.snapshot(self.livreur.partner_id)
        self.assertEqual(snap["earned"], run.price)
        self.assertEqual(snap["available"], run.price)
        self.assertEqual(snap["kind"], "delivery_fees")
        self.assertEqual(snap["label"], "Frais de livraison")

    def test_wallet_snapshot_fournisseur(self):
        order, run = self._delivered_order()
        snap = wallet.snapshot(self.shop.partner_id)
        self.assertEqual(snap["earned"], 10000.0)  # product_total only
        self.assertEqual(snap["kind"], "product_sales")

    def test_withdraw_flow(self):
        order, run = self._delivered_order()
        result = wallet.withdraw(self.env, self.livreur, run.price, note="Test")
        self.assertEqual(result["message"], "Retrait initialise avec succes")
        self.assertEqual(result["withdrawal"]["status"], "completed")
        self.assertEqual(result["wallet"]["available"], 0.0)
        payload = wallet.wallet_payload(self.env, self.livreur)
        self.assertEqual(len(payload["history"]), 1)
        self.assertEqual(payload["history"][0]["note"], "Test")
        with self.assertRaises(wallet.WalletInsufficient):
            wallet.withdraw(self.env, self.livreur, 100)
        with self.assertRaises(ValueError):
            wallet.withdraw(self.env, self.livreur, 0)
        with self.assertRaises(ValueError):
            wallet.withdraw(self.env, self.livreur, "abc")

    # ---------- cancellation ----------
    def test_cancel_paid_refunds_20_percent(self):
        result = checkout.create_order_with_payment(
            self.env, self.client,
            {"supplier_id": self.shop.partner_id.id, "mode": "delivery",
             "payment_method": "tmoney", "delivery_address": "Lome",
             "delivery_lat": 6.16, "delivery_lon": 1.21,
             "lines": [{"product_id": self.product.id, "quantity": 2}]},
        )
        order = self.env["likdelivery.order"].browse(result["order_id"])
        self.assertEqual(order.payment_status, "paid")
        cancel = cancellation.cancel_order(self.env, self.client, order)
        self.assertEqual(cancel["penalty_percent"], 80.0)
        self.assertEqual(cancel["penalty"], round(order.total * 0.8, 0))
        self.assertEqual(cancel["refund"], order.total - cancel["penalty"])
        tx = self.env["likdelivery.payment.transaction"].search(
            [("order_id", "=", order.id), ("provider", "=", "refund")]
        )
        self.assertEqual(len(tx), 1)
        self.assertTrue(tx.provider_ref.startswith("REF-"))
        self.assertEqual(tx.amount, cancel["refund"])
        self.assertEqual(order.state, "CANCELLED")

    def test_cancel_unpaid_no_transaction(self):
        result = checkout.create_legacy_order(
            self.env, self.client,
            {"supplier_id": self.shop.partner_id.id, "mode": "delivery",
             "payment_method": "cash_on_delivery", "delivery_address": "Lome",
             "delivery_lat": 6.16, "delivery_lon": 1.21,
             "lines": [{"product_id": self.product.id, "quantity": 1}]},
        )
        order = self.env["likdelivery.order"].browse(result["order_id"])
        cancel = cancellation.cancel_order(self.env, self.client, order)
        tx = self.env["likdelivery.payment.transaction"].search(
            [("order_id", "=", order.id)]
        )
        self.assertEqual(len(tx), 0)
        notif = self.env["likdelivery.notification"].search(
            [("user_id", "=", self.client.partner_id.id)], order="id desc", limit=1
        )
        self.assertIn("redevable", notif.body)
        self.assertIn(f"{cancel['penalty']:.0f} XOF", notif.body)

    def test_cancel_blocked_and_bola(self):
        order, run = self._delivered_order()
        with self.assertRaises(ValueError):
            cancellation.cancel_order(self.env, self.client, order)
        result = checkout.create_legacy_order(
            self.env, self.client,
            {"supplier_id": self.shop.partner_id.id, "mode": "pickup",
             "payment_method": "pay_at_pickup",
             "lines": [{"product_id": self.product.id, "quantity": 1}]},
        )
        order2 = self.env["likdelivery.order"].browse(result["order_id"])
        with self.assertRaises(order_lifecycle.OrderForbidden):
            cancellation.cancel_order(self.env, self.client2, order2)
        # gap LK-SEC-02 ported: a non-client role may cancel any order
        cancellation.cancel_order(self.env, self.admin, order2)
        self.assertEqual(order2.state, "CANCELLED")

    # ---------- rating ----------
    def test_rate_order_and_average_recompute(self):
        order, run = self._delivered_order()
        result = rating.rate(
            self.env, self.client, {"order_id": order.id, "stars": 4, "comment": "Bien"}
        )
        self.assertEqual(order.rating, 4)
        self.assertEqual(run.rating, 4)
        self.assertEqual(result["livreur_average_rating"], 4.0)
        # second delivery, second rating → average recomputed over all runs
        order2, run2 = self._delivered_order()
        result2 = rating.rate(self.env, self.client, {"order_id": order2.id, "stars": 2})
        self.assertEqual(result2["livreur_average_rating"], 3.0)
        self.assertEqual(self.livreur.partner_id.lik_average_rating, 3.0)

    def test_rate_guards(self):
        result = checkout.create_legacy_order(
            self.env, self.client,
            {"supplier_id": self.shop.partner_id.id, "mode": "pickup",
             "payment_method": "pay_at_pickup",
             "lines": [{"product_id": self.product.id, "quantity": 1}]},
        )
        order = self.env["likdelivery.order"].browse(result["order_id"])
        with self.assertRaises(ValueError) as ctx:
            rating.rate(self.env, self.client, {"order_id": order.id, "stars": 5})
        self.assertIn("apres la livraison", str(ctx.exception))
        order2, run2 = self._delivered_order()
        with self.assertRaises(ValueError):
            rating.rate(self.env, self.client, {"order_id": order2.id, "stars": 6})
        with self.assertRaises(ValueError):
            rating.rate(self.env, self.client2, {"order_id": order2.id, "stars": 5})
        with self.assertRaises(order_lifecycle.OrderForbidden):
            rating.rate(self.env, self.client2, {"run_id": run2.id, "stars": 5})
        with self.assertRaises(ValueError):
            rating.rate(self.env, self.client, {"stars": 5})
