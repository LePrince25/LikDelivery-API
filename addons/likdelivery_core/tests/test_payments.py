"""Notification + payment service tests (S10) — LK-NOT-01, LK-PAY-01..03."""

from odoo.tests import TransactionCase, tagged

from ..services import checkout, notification, payment_service
from ..services.order_lifecycle import OrderNotFound


@tagged("post_install", "-at_install", "likdelivery")
class TestNotificationPayment(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env["res.partner"]

        def mkuser(name, phone, role, **kw):
            partner = Partner.create(dict(name=name, phone=phone, lik_role=role, **kw))
            return cls.env["likdelivery.user"].create(
                {"name": name, "phone": phone, "partner_id": partner.id}
            )

        cls.client = mkuser("Cli S10", "+22876000001", "client")
        cls.client2 = mkuser("Cli S10b", "+22876000002", "client")
        cls.shop = mkuser(
            "Shop S10", "+22876000003", "fournisseur",
            lik_validated_by_admin=True, lik_company_name="Shop S10",
        )
        cls.product = cls.env["likdelivery.product"].create({
            "name": "P S10", "supplier_id": cls.shop.partner_id.id,
            "price": 3000, "stock": 20, "active": True,
        })

    def _order(self):
        result = checkout.create_legacy_order(
            self.env, self.client,
            {"supplier_id": self.shop.partner_id.id, "mode": "pickup",
             "payment_method": "pay_at_pickup",
             "lines": [{"product_id": self.product.id, "quantity": 1}]},
        )
        return self.env["likdelivery.order"].browse(result["order_id"])

    # ---------- notifications ----------
    def test_list_own_and_guest_phone(self):
        notification.notify(
            self.env, partner=self.client.partner_id, title="T1", body="B1"
        )
        notification.notify(
            self.env, guest_phone=self.client.partner_id.phone, title="T2", body="B2"
        )
        notification.notify(
            self.env, partner=self.client2.partner_id, title="T3", body="B3"
        )
        titles = [n["title"] for n in notification.list_for(self.env, self.client)]
        self.assertIn("T1", titles)
        self.assertIn("T2", titles)  # guest_phone matches own phone
        self.assertNotIn("T3", titles)

    def test_mark_read_ownership(self):
        note = notification.notify(
            self.env, partner=self.client.partner_id, title="Read", body="B"
        )
        other = notification.notify(
            self.env, partner=self.client2.partner_id, title="Other", body="B"
        )
        notification.mark_read(self.env, self.client, note.id)
        self.assertTrue(note.is_read)
        # cannot mark someone else's (silent no-op, as reference)
        notification.mark_read(self.env, self.client, other.id)
        self.assertFalse(other.is_read)

    # ---------- payments ----------
    def test_initiate_and_confirm_success(self):
        order = self._order()
        init = payment_service.initiate(
            self.env, self.client,
            {"target_type": "order", "target_id": order.id, "provider": "flooz",
             "phone": "+22876000001"},
        )
        self.assertEqual(init["status"], "pending")
        self.assertTrue(init["reference"].startswith("PAY-"))
        self.assertEqual(init["amount"], order.total)
        st = payment_service.status(self.env, init["reference"])
        self.assertEqual(st["provider"], "flooz")
        conf = payment_service.confirm(
            self.env, self.client, init["reference"], {"simulate_success": True}
        )
        self.assertEqual(conf["status"], "success")
        self.assertEqual(order.payment_status, "paid")
        tx = self.env["likdelivery.payment.transaction"].search(
            [("reference", "=", init["reference"])]
        )
        self.assertTrue(tx.provider_ref.startswith("PROV-"))

    def test_confirm_failure(self):
        order = self._order()
        init = payment_service.initiate(
            self.env, None, {"target_type": "order", "target_id": order.id}
        )
        conf = payment_service.confirm(
            self.env, None, init["reference"], {"simulate_success": False}
        )
        self.assertEqual(conf["status"], "failed")
        tx = self.env["likdelivery.payment.transaction"].search(
            [("reference", "=", init["reference"])]
        )
        self.assertEqual(tx.failure_reason, "Echec simulate")
        self.assertEqual(order.payment_status, "pending")

    def test_initiate_courier_and_invalid(self):
        req = checkout.create_courier_request(
            self.env, self.client,
            {"pickup_address": "A", "pickup_lat": 6.17, "pickup_lon": 1.22,
             "dropoff_address": "B", "dropoff_lat": 6.16, "dropoff_lon": 1.21},
        )
        init = payment_service.initiate(
            self.env, None, {"target_type": "courier", "target_id": req["id"]}
        )
        self.assertEqual(init["amount"], req["price"])
        payment_service.confirm(self.env, None, init["reference"], {})
        courier = self.env["likdelivery.courier.request"].browse(req["id"])
        self.assertEqual(courier.payment_status, "paid")
        with self.assertRaises(OrderNotFound):
            payment_service.initiate(
                self.env, None, {"target_type": "order", "target_id": 999999}
            )
        with self.assertRaises(OrderNotFound):
            payment_service.status(self.env, "PAY-UNKNOWN")
