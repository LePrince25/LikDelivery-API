"""Order creation tests (S5) — golden expectations from the reference flows
LK-CHK-01/03/04/05 and LK-PAY-01/02."""

from odoo.tests import TransactionCase, tagged

from ..services import cart_service, checkout, pricing


@tagged("post_install", "-at_install", "likdelivery")
class TestOrderCreation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env["res.partner"]
        Product = cls.env["likdelivery.product"]
        cls.client = Partner.create({
            "name": "Cli S5", "lik_role": "client", "phone": "+22871000001",
        })
        cls.lik_client = cls.env["likdelivery.user"].create(
            {"name": "Cli S5", "phone": "+22871000001", "partner_id": cls.client.id}
        )
        cls.shop_a = Partner.create({
            "name": "Shop A", "lik_role": "fournisseur", "lik_validated_by_admin": True,
            "lik_company_name": "Shop A", "partner_latitude": 6.1725,
            "partner_longitude": 1.2253, "street": "Rue A",
        })
        cls.shop_b = Partner.create({
            "name": "Shop B", "lik_role": "fournisseur", "lik_validated_by_admin": True,
            "lik_company_name": "Shop B", "partner_latitude": 6.15,
            "partner_longitude": 1.24,
        })
        cls.p_a = Product.create({
            "name": "PA", "supplier_id": cls.shop_a.id, "price": 2000,
            "stock": 10, "active": True,
        })
        cls.p_af = Product.create({
            "name": "PAF", "supplier_id": cls.shop_a.id, "price": 1000,
            "stock": 5, "active": True, "fragile": True,
        })
        cls.p_b = Product.create({
            "name": "PB", "supplier_id": cls.shop_b.id, "price": 3000,
            "stock": 8, "active": True,
        })
        cls.soc = Partner.create({
            "name": "Soc", "lik_role": "societe", "lik_validated_by_admin": True,
            "lik_company_name": "Soc",
        })

    def _cart(self, product, qty):
        cart_service.add_to_cart(self.env, self.lik_client, product.id, qty)

    def _expected_fee(self, supplier, fragile=False, high_value=False):
        dist = pricing.haversine(
            supplier.partner_latitude, supplier.partner_longitude,
            checkout.DEFAULT_DELIVERY_LAT, checkout.DEFAULT_DELIVERY_LON,
        )
        return pricing.calculate_delivery_fee(
            dist, is_fragile=fragile, high_value=high_value
        )[0]

    def test_multi_cod_two_suppliers(self):
        self._cart(self.p_a, 2)
        self._cart(self.p_af, 1)
        self._cart(self.p_b, 3)
        result = checkout.create_multi_orders(
            self.env, self.lik_client,
            {"mode": "delivery", "payment_method": "cash_on_delivery",
             "delivery_address": "Adidogome", "payment_phone": "+22899990000"},
        )
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["skipped"], [])
        by_supplier = {o["supplier"]: o for o in result["orders"]}
        oa = by_supplier["Shop A"]
        # A: 2×2000 + 1×1000 = 5000, fragile → fee with ×1.2
        self.assertEqual(oa["product_total"], 5000.0)
        self.assertEqual(oa["delivery_fee"], self._expected_fee(self.shop_a, fragile=True))
        self.assertEqual(oa["total"], 5000.0 + oa["delivery_fee"])
        self.assertEqual(oa["payment_status"], "pending")
        ob = by_supplier["Shop B"]
        self.assertEqual(ob["product_total"], 9000.0)
        self.assertEqual(ob["delivery_fee"], self._expected_fee(self.shop_b))
        # stock decremented (A: 10-2, AF: 5-1, B: 8-3)
        self.assertEqual(self.p_a.stock, 8)
        self.assertEqual(self.p_af.stock, 4)
        self.assertEqual(self.p_b.stock, 5)
        # cart cleared
        self.assertEqual(cart_service.cart_payload(self.env, lik_user=self.lik_client), [])
        # COD → no transactions on the created orders; suppliers notified
        order_ids = [o["order_id"] for o in result["orders"]]
        self.assertEqual(
            self.env["likdelivery.payment.transaction"].search_count(
                [("order_id", "in", order_ids)]
            ),
            0,
        )
        notifs = self.env["likdelivery.notification"].search(
            [("user_id", "in", [self.shop_a.id, self.shop_b.id])]
        )
        self.assertEqual(len(notifs), 2)
        # recipient contact stored on the order
        order = self.env["likdelivery.order"].browse(oa["order_id"])
        self.assertEqual(order.guest_phone, "+22899990000")
        self.assertEqual(order.delivery_address, "Adidogome")
        self.assertTrue(order.is_fragile)
        self.assertFalse(by_supplier and order.preferred_societe_id)

    def test_multi_online_payment_success(self):
        self._cart(self.p_a, 1)
        result = checkout.create_multi_orders(
            self.env, self.lik_client,
            {"mode": "delivery", "payment_method": "tmoney",
             "delivery_address": "Lome"},
        )
        order_payload = result["orders"][0]
        self.assertEqual(order_payload["payment_status"], "paid")
        tx = self.env["likdelivery.payment.transaction"].search(
            [("order_id", "=", order_payload["order_id"])]
        )
        self.assertEqual(len(tx), 1)
        self.assertEqual(tx.state, "success")
        self.assertEqual(tx.provider, "tmoney")
        # Reference quirk: provider_ref in multi = 12 hex chars, NO PROV- prefix
        self.assertEqual(len(tx.provider_ref), 12)
        self.assertNotIn("PROV-", tx.provider_ref)

    def test_multi_pickup_normalization(self):
        self._cart(self.p_a, 1)
        result = checkout.create_multi_orders(
            self.env, self.lik_client,
            {"mode": "pickup", "payment_method": "cash_on_delivery"},
        )
        self.assertEqual(result["payment_method"], "pay_at_pickup")
        order = self.env["likdelivery.order"].browse(result["orders"][0]["order_id"])
        self.assertEqual(order.delivery_fee, 0.0)
        self.assertEqual(order.delivery_address, "Rue A")  # supplier address
        self.assertEqual(order.payment_method, "pay_at_pickup")

    def test_multi_validation_errors(self):
        self._cart(self.p_a, 1)
        with self.assertRaises(checkout.CheckoutError):
            checkout.create_multi_orders(self.env, self.lik_client, {"mode": "rocket"})
        with self.assertRaises(checkout.CheckoutError):
            checkout.create_multi_orders(
                self.env, self.lik_client, {"mode": "delivery", "delivery_address": " "}
            )
        with self.assertRaises(checkout.CheckoutError):
            checkout.create_multi_orders(
                self.env, self.lik_client,
                {"mode": "delivery", "payment_method": "pay_at_pickup",
                 "delivery_address": "Lome"},
            )

    def test_multi_skips_unavailable_supplier(self):
        self.shop_b.lik_validated_by_admin = False
        self._cart(self.p_a, 1)
        self._cart(self.p_b, 1)
        result = checkout.create_multi_orders(
            self.env, self.lik_client,
            {"mode": "delivery", "delivery_address": "Lome"},
        )
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["orders"][0]["supplier"], "Shop A")
        self.assertEqual(len(result["skipped"]), 1)
        self.assertIn("non valide par l'admin", result["skipped"][0])

    def test_multi_all_unavailable_raises(self):
        self.shop_a.lik_validated_by_admin = False
        self._cart(self.p_a, 1)
        with self.assertRaises(checkout.CheckoutError) as ctx:
            checkout.create_multi_orders(
                self.env, self.lik_client,
                {"mode": "delivery", "delivery_address": "Lome"},
            )
        self.assertIn("Aucune commande creee", str(ctx.exception))

    def test_preferred_societe_profile_fallback(self):
        self.client.lik_preferred_societe_id = self.soc
        self._cart(self.p_a, 1)
        result = checkout.create_multi_orders(
            self.env, self.lik_client,
            {"mode": "delivery", "delivery_address": "Lome"},
        )
        order = self.env["likdelivery.order"].browse(result["orders"][0]["order_id"])
        self.assertEqual(order.preferred_societe_id, self.soc)
        notif = self.env["likdelivery.notification"].search(
            [("user_id", "=", self.soc.id)]
        )
        self.assertEqual(len(notif), 1)
        self.assertIn("choisie par le client", notif.body)

    def test_legacy_guest_order_strict_stock(self):
        # strict: qty > stock → error (whole order aborted)
        with self.assertRaises(checkout.CheckoutError) as ctx:
            checkout.create_legacy_order(
                self.env, None,
                {"supplier_id": self.shop_a.id, "mode": "delivery",
                 "delivery_address": "Lome", "delivery_lat": 6.16, "delivery_lon": 1.21,
                 "guest_phone": "+22877777777",
                 "lines": [{"product_id": self.p_a.id, "quantity": 999}]},
            )
        self.assertIn("Stock insuffisant", str(ctx.exception))
        result = checkout.create_legacy_order(
            self.env, None,
            {"supplier_id": self.shop_a.id, "mode": "delivery",
             "delivery_address": "Lome", "delivery_lat": 6.16, "delivery_lon": 1.21,
             "guest_phone": "+22877777777",
             "lines": [{"product_id": self.p_af.id, "quantity": 2}]},
        )
        order = self.env["likdelivery.order"].browse(result["order_id"])
        self.assertFalse(order.client_id)
        self.assertEqual(order.guest_phone, "+22877777777")
        # legacy fee: distance*300 ×1.2 fragile only (no night / high-value)
        dist = pricing.haversine(6.1725, 1.2253, 6.16, 1.21)
        fee, _ = pricing.calculate_legacy_fee(dist, is_fragile=True)
        self.assertEqual(order.delivery_fee, fee)
        self.assertEqual(order.total, 2000.0 + fee)
        self.assertEqual(result["otp"], order.otp_code)

    def test_order_with_payment_simulation(self):
        base = {
            "supplier_id": self.shop_a.id, "mode": "delivery",
            "delivery_address": "Lome", "delivery_lat": 6.16, "delivery_lon": 1.21,
            "payment_method": "flooz",
            "lines": [{"product_id": self.p_a.id, "quantity": 1}],
        }
        ok_result = checkout.create_order_with_payment(
            self.env, self.lik_client, dict(base)
        )
        self.assertEqual(ok_result["payment"]["status"], "success")
        self.assertTrue(ok_result["payment"]["provider_ref"].startswith("PROV-"))
        order = self.env["likdelivery.order"].browse(ok_result["order_id"])
        self.assertEqual(order.payment_status, "paid")

        ko_result = checkout.create_order_with_payment(
            self.env, self.lik_client,
            dict(base, simulate_payment_success=False),
        )
        self.assertEqual(ko_result["payment"]["status"], "failed")
        failed_order = self.env["likdelivery.order"].browse(ko_result["order_id"])
        self.assertEqual(failed_order.payment_status, "failed")
        tx = self.env["likdelivery.payment.transaction"].search(
            [("order_id", "=", ko_result["order_id"])]
        )
        self.assertEqual(tx.failure_reason, "Paiement refuse (simulation)")

    def test_courier_request_pricing_and_guest(self):
        result = checkout.create_courier_request(
            self.env, None,
            {"pickup_address": "A", "pickup_lat": 6.1725, "pickup_lon": 1.2253,
             "dropoff_address": "B", "dropoff_lat": 6.16, "dropoff_lon": 1.21,
             "is_fragile": True, "guest_phone": "+22866666666"},
        )
        req = self.env["likdelivery.courier.request"].browse(result["id"])
        dist = pricing.haversine(6.1725, 1.2253, 6.16, 1.21)
        self.assertEqual(req.distance_km, round(dist, 2))
        self.assertEqual(req.price, round(dist * 300 * 1.2, 0))
        self.assertTrue(req.code.startswith("CRS-"))
        self.assertEqual(req.guest_phone, "+22866666666")
        notif = self.env["likdelivery.notification"].search(
            [("guest_phone", "=", "+22866666666")]
        )
        self.assertEqual(len(notif), 1)
        self.assertIn("Course colis creee", notif.title)
