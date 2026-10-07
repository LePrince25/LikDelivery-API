"""Golden checkout tests (S4 acceptance gate).

Hand-computed expectations from the reference formulas (LK-CRT-01,
LK-CHK-02): stock capping, fragile/high-value propagation (including the
high_value quirk on non-included items), fee math, and the due-now /
due-on-delivery split per mode + payment method.
"""

from odoo.tests import TransactionCase, tagged

from ..services import cart_service, checkout, pricing


@tagged("post_install", "-at_install", "likdelivery")
class TestCartAndCheckout(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env["res.partner"]
        Product = cls.env["likdelivery.product"]
        cls.client = Partner.create({"name": "Cli Test", "lik_role": "client"})
        cls.lik_client = cls.env["likdelivery.user"].create(
            {"name": "Cli Test", "phone": "+22870000001", "partner_id": cls.client.id}
        )
        # No opening hours → always open; validated → available
        cls.shop_a = Partner.create({
            "name": "Shop A", "lik_role": "fournisseur", "lik_validated_by_admin": True,
            "lik_company_name": "Shop A", "partner_latitude": 6.1725, "partner_longitude": 1.2253,
        })
        cls.shop_b = Partner.create({
            "name": "Shop B", "lik_role": "fournisseur", "lik_validated_by_admin": True,
            "lik_company_name": "Shop B", "partner_latitude": 6.15, "partner_longitude": 1.24,
        })
        cls.p_a1 = Product.create({
            "name": "A1", "supplier_id": cls.shop_a.id, "price": 1000, "stock": 10, "active": True,
        })
        cls.p_a2 = Product.create({
            "name": "A2 fragile", "supplier_id": cls.shop_a.id, "price": 500, "stock": 3,
            "active": True, "fragile": True,
        })
        cls.p_b1 = Product.create({
            "name": "B1 hv", "supplier_id": cls.shop_b.id, "price": 60000, "stock": 5, "active": True,
        })

    def _preview(self, **kw):
        return checkout.preview(self.env, self.lik_client, **kw)

    def test_cart_accumulate_and_remove(self):
        env = self.env
        cart_service.add_to_cart(env, self.lik_client, self.p_a1.id, 2)
        cart_service.add_to_cart(env, self.lik_client, self.p_a1.id, 3)
        payload = cart_service.cart_payload(env, lik_user=self.lik_client)
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["quantity"], 5)
        self.assertEqual(payload[0]["unit_price"], 1000)
        self.assertEqual(payload[0]["supplier_name"], "Shop A")
        cart_service.add_to_cart(env, self.lik_client, self.p_a1.id, -2)
        payload = cart_service.cart_payload(env, lik_user=self.lik_client)
        self.assertEqual(payload[0]["quantity"], 3)
        cart_service.add_to_cart(env, self.lik_client, self.p_a1.id, -3)
        self.assertEqual(cart_service.cart_payload(env, lik_user=self.lik_client), [])

    def test_cart_invalid_product(self):
        with self.assertRaises(ValueError):
            cart_service.add_to_cart(self.env, self.lik_client, 999999, 1)
        self.p_a1.active = False
        with self.assertRaises(ValueError):
            cart_service.add_to_cart(self.env, self.lik_client, self.p_a1.id, 1)
        self.p_a1.active = True

    def test_empty_cart_preview_raises(self):
        with self.assertRaises(ValueError):
            self._preview()

    def test_guest_cart_by_token(self):
        self.env["likdelivery.cart.session"].create({
            "session_token": "tok123", "supplier_id": self.shop_a.id,
            "product_id": self.p_a1.id, "quantity": 2,
        })
        payload = cart_service.cart_payload(self.env, session_token="tok123")
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["quantity"], 2)

    def test_preview_delivery_cod(self):
        env = self.env
        cart_service.add_to_cart(env, self.lik_client, self.p_a1.id, 2)
        cart_service.add_to_cart(env, self.lik_client, self.p_a2.id, 10)  # capped to stock 3
        cart_service.add_to_cart(env, self.lik_client, self.p_b1.id, 1)

        result = self._preview(mode="delivery", payment_method="cash_on_delivery")
        groups = {g["supplier_id"]: g for g in result["groups"]}
        self.assertEqual(len(groups), 2)

        ga = groups[self.shop_a.id]
        # 2×1000 + min(10,3)×500 = 3500; fragile from A2
        self.assertEqual(ga["product_total"], 3500.0)
        self.assertEqual(len(ga["lines"]), 2)
        self.assertEqual(ga["lines"][1]["quantity"], 3)
        dist_a = pricing.haversine(6.1725, 1.2253, checkout.DEFAULT_DELIVERY_LAT, checkout.DEFAULT_DELIVERY_LON)
        fee_a, dist_a_r = pricing.calculate_delivery_fee(dist_a, is_fragile=True, high_value=False)
        self.assertEqual(ga["delivery_fee"], fee_a)
        self.assertEqual(ga["distance_km"], dist_a_r)
        self.assertTrue(ga["available"])
        self.assertIsNone(ga["reason"])

        gb = groups[self.shop_b.id]
        self.assertEqual(gb["product_total"], 60000.0)
        dist_b = pricing.haversine(6.15, 1.24, checkout.DEFAULT_DELIVERY_LAT, checkout.DEFAULT_DELIVERY_LON)
        fee_b, _ = pricing.calculate_delivery_fee(dist_b, is_fragile=False, high_value=True)
        self.assertEqual(gb["delivery_fee"], fee_b)

        self.assertEqual(result["products_total"], 63500.0)
        self.assertEqual(result["delivery_total"], fee_a + fee_b)
        self.assertEqual(result["grand_total"], 63500.0 + fee_a + fee_b)
        # COD delivery → everything due on delivery, nothing now
        self.assertEqual(result["amount_due_now"], 0.0)
        self.assertEqual(result["amount_due_on_delivery"], result["grand_total"])
        self.assertFalse(result["pay_now"])

    def test_preview_delivery_online(self):
        cart_service.add_to_cart(self.env, self.lik_client, self.p_a1.id, 1)
        result = self._preview(mode="delivery", payment_method="tmoney")
        self.assertEqual(result["amount_due_now"], result["grand_total"])
        self.assertEqual(result["amount_due_on_delivery"], 0.0)
        self.assertTrue(result["pay_now"])

    def test_preview_pickup_no_fee(self):
        cart_service.add_to_cart(self.env, self.lik_client, self.p_a1.id, 2)
        result = self._preview(mode="pickup", payment_method="pay_at_pickup")
        self.assertEqual(result["delivery_total"], 0.0)
        self.assertEqual(result["grand_total"], 2000.0)
        # pay_at_pickup → nothing due now (paid at the shop)
        self.assertEqual(result["amount_due_now"], 0.0)
        self.assertEqual(result["amount_due_on_delivery"], 0.0)
        self.assertFalse(result["pay_now"])

    def test_high_value_quirk_on_zero_stock_item(self):
        """Reference quirk: high_value inspects items even with stock 0 —
        the fee keeps the ×1.5 multiplier although no line is included."""
        self.p_b1.stock = 0
        self.p_b1.supplier_id = self.shop_a  # high-value product in shop A cart
        cart_service.add_to_cart(self.env, self.lik_client, self.p_b1.id, 1)
        result = self._preview(mode="delivery")
        ga = [g for g in result["groups"] if g["supplier_id"] == self.shop_a.id][0]
        # B1 capped to 0 → no lines at all, but high_value still true
        self.assertEqual(ga["lines"], [])
        self.assertEqual(ga["product_total"], 0.0)
        dist = pricing.haversine(6.1725, 1.2253, checkout.DEFAULT_DELIVERY_LAT, checkout.DEFAULT_DELIVERY_LON)
        fee, _ = pricing.calculate_delivery_fee(dist, is_fragile=False, high_value=True)
        self.assertEqual(ga["delivery_fee"], fee)
        self.assertNotEqual(fee, pricing.calculate_delivery_fee(dist, high_value=False)[0])
