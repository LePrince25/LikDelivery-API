"""Assignment & claim tests (S7 gate) — LK-ASN-01..05, LK-CLM-01/02, LK-MSN-07."""

from odoo.tests import TransactionCase, tagged

from ..services import assignment, checkout, mission_lifecycle, order_lifecycle


@tagged("post_install", "-at_install", "likdelivery")
class TestAssignment(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env["res.partner"]

        def mkuser(name, phone, role, **kw):
            partner = Partner.create(dict(name=name, phone=phone, lik_role=role, **kw))
            return cls.env["likdelivery.user"].create(
                {"name": name, "phone": phone, "partner_id": partner.id}
            )

        cls.client = mkuser("Cli S7", "+22873000001", "client")
        cls.shop = mkuser(
            "Shop S7", "+22873000002", "fournisseur",
            lik_validated_by_admin=True, lik_company_name="Shop S7",
            partner_latitude=6.1725, partner_longitude=1.2253,
        )
        cls.shop2 = mkuser(
            "Shop S7b", "+22873000003", "fournisseur",
            lik_validated_by_admin=True, lik_company_name="Shop S7b",
        )
        cls.livreur = mkuser("Liv S7", "+22873000004", "livreur")
        cls.livreur2 = mkuser("Liv S7b", "+22873000005", "livreur")
        cls.shop_driver = mkuser("LivBout S7", "+22873000006", "livreur")
        cls.soc = mkuser("Soc S7", "+22873000007", "societe", lik_validated_by_admin=True)
        cls.fleet_driver = mkuser("LivFleet S7", "+22873000008", "livreur")
        cls.admin = mkuser("Admin S7", "+22873000009", "admin")
        cls.product = cls.env["likdelivery.product"].create({
            "name": "P S7", "supplier_id": cls.shop.partner_id.id,
            "price": 2000, "stock": 50, "active": True,
        })
        cls.env["likdelivery.fleet.driver"].create({
            "societe_id": cls.soc.partner_id.id,
            "livreur_id": cls.fleet_driver.partner_id.id,
            "origin": "external", "is_active": True,
        })
        cls.env["likdelivery.shop.driver"].create({
            "supplier_id": cls.shop.partner_id.id,
            "livreur_id": cls.shop_driver.partner_id.id,
            "is_active": True,
        })

    def _order(self, societe=False, shop=None, payment="cash_on_delivery"):
        data = {
            "supplier_id": (shop or self.shop).partner_id.id,
            "mode": "delivery", "payment_method": payment,
            "delivery_address": "Lome", "delivery_lat": 6.16, "delivery_lon": 1.21,
            "lines": [{"product_id": self.product.id, "quantity": 1}],
        }
        if societe:
            data["preferred_societe_id"] = self.soc.partner_id.id
        result = checkout.create_legacy_order(self.env, self.client, data)
        order = self.env["likdelivery.order"].browse(result["order_id"])
        if societe:
            order.preferred_societe_id = self.soc.partner_id
        return order

    # ----- assign_livreur_to_order -----
    def test_assign_creates_run_and_syncs_order(self):
        order = self._order(shop=self.shop2)  # no shop drivers
        run = assignment.assign_livreur_to_order(
            self.env, order, self.livreur.partner_id, self.admin
        )
        self.assertEqual(run.state, "ACCEPTED")
        self.assertTrue(run.otp_code)
        self.assertTrue(run.qr_token)
        self.assertGreater(run.price, 0)
        self.assertEqual(order.state, "OUT_FOR_DELIVERY")
        self.assertFalse(order.open_for_platform_claim)
        notif = self.env["likdelivery.notification"].search(
            [("user_id", "=", self.livreur.partner_id.id)], order="id desc", limit=1
        )
        self.assertIn("Nouvelle mission", notif.title)
        self.assertIn(run.otp_code, notif.body)

    def test_assign_double_rejected(self):
        order = self._order(shop=self.shop2)
        assignment.assign_livreur_to_order(
            self.env, order, self.livreur.partner_id, self.admin
        )
        with self.assertRaises(ValueError) as ctx:
            assignment.assign_livreur_to_order(
                self.env, order, self.livreur2.partner_id, self.admin
            )
        self.assertIn("deja assigne", str(ctx.exception))

    def test_assign_pickup_mode_rejected(self):
        data = {
            "supplier_id": self.shop2.partner_id.id, "mode": "pickup",
            "payment_method": "pay_at_pickup",
            "lines": [{"product_id": self.product.id, "quantity": 1}],
        }
        result = checkout.create_legacy_order(self.env, self.client, data)
        order = self.env["likdelivery.order"].browse(result["order_id"])
        with self.assertRaises(ValueError):
            assignment.assign_livreur_to_order(
                self.env, order, self.livreur.partner_id, self.admin
            )

    # ----- assign_by_actor (E42) -----
    def test_fournisseur_must_use_shop_driver(self):
        order = self._order()  # shop has a shop driver
        with self.assertRaises(ValueError) as ctx:
            assignment.assign_by_actor(
                self.env, self.shop, order, self.livreur.partner_id.id
            )
        self.assertIn("pas associe a votre boutique", str(ctx.exception))
        result = assignment.assign_by_actor(
            self.env, self.shop, order, self.shop_driver.partner_id.id
        )
        self.assertEqual(result["source"], "boutique")
        # Reference quirk (LK-SEC-13): the post-assign "ready bump" is
        # unreachable — assignment already set OUT_FOR_DELIVERY, so the run
        # stays ACCEPTED until the driver acts.
        self.assertEqual(result["status"], "ACCEPTED")
        self.assertEqual(order.state, "OUT_FOR_DELIVERY")

    def test_fournisseur_blocked_when_societe_preferred(self):
        order = self._order(societe=True)
        with self.assertRaises(order_lifecycle.OrderForbidden):
            assignment.assign_by_actor(
                self.env, self.shop, order, self.shop_driver.partner_id.id
            )

    def test_societe_assigns_fleet_only(self):
        order = self._order(societe=True)
        with self.assertRaises(ValueError) as ctx:
            assignment.assign_by_actor(
                self.env, self.soc, order, self.livreur.partner_id.id
            )
        self.assertIn("votre flotte", str(ctx.exception))
        result = assignment.assign_by_actor(
            self.env, self.soc, order, self.fleet_driver.partner_id.id
        )
        self.assertEqual(result["source"], "societe")

    def test_admin_assigns_any(self):
        order = self._order()
        result = assignment.assign_by_actor(
            self.env, self.admin, order, self.livreur.partner_id.id
        )
        self.assertEqual(result["source"], "admin")

    # ----- init_handover (E39) -----
    def test_handover_requires_shop_assign_first(self):
        order = self._order()  # shop has drivers
        with self.assertRaises(ValueError) as ctx:
            assignment.init_handover(self.env, self.shop, order)
        self.assertIn("livreurs associes", str(ctx.exception))

    def test_handover_opens_platform_pool(self):
        order = self._order(shop=self.shop2)  # no shop drivers
        result = assignment.init_handover(self.env, self.shop2, order)
        self.assertTrue(order.open_for_platform_claim)
        self.assertEqual(order.state, "PICKUP_IN_PROGRESS")
        self.assertEqual(result["handover_for"], "plateforme")
        # idempotent second call
        again = assignment.init_handover(self.env, self.shop2, order)
        self.assertIn("deja initialise", again["message"])

    def test_handover_payment_not_ready(self):
        order = self._order(shop=self.shop2, payment="tmoney")
        order.payment_status = "pending"
        with self.assertRaises(ValueError) as ctx:
            assignment.init_handover(self.env, self.shop2, order)
        self.assertIn("paiement", str(ctx.exception).lower())

    # ----- available_orders / claim (E48/E49) -----
    def test_available_orders_pools(self):
        env = self.env
        o_shop = self._order()                     # shop pool
        o_soc = self._order(societe=True)          # societe pool
        o_open = self._order(shop=self.shop2)      # platform pool (after handover)
        assignment.init_handover(env, self.shop2, o_open)

        shop_driver_orders = assignment.available_orders(env, self.shop_driver)
        self.assertIn(o_shop.id, [o["id"] for o in shop_driver_orders])
        self.assertEqual(
            [o for o in shop_driver_orders if o["id"] == o_shop.id][0]["claim_source"],
            "boutique",
        )
        # random livreur: sees only the open platform order
        liv_orders = assignment.available_orders(env, self.livreur)
        liv_ids = [o["id"] for o in liv_orders]
        self.assertIn(o_open.id, liv_ids)
        self.assertNotIn(o_shop.id, liv_ids)
        self.assertNotIn(o_soc.id, liv_ids)
        # fleet livreur sees the societe order
        fleet_orders = assignment.available_orders(env, self.fleet_driver)
        fleet_ids = [o["id"] for o in fleet_orders]
        self.assertIn(o_soc.id, fleet_ids)
        self.assertEqual(
            [o for o in fleet_orders if o["id"] == o_soc.id][0]["claim_source"],
            "societe",
        )

    def test_claim_guards(self):
        env = self.env
        # shop order: non-shop livreur rejected
        order = self._order()
        with self.assertRaises(order_lifecycle.OrderForbidden) as ctx:
            assignment.claim_order(env, self.livreur, order)
        self.assertIn("reservee aux livreurs de la boutique", str(ctx.exception))
        # societe order: non-fleet rejected
        soc_order = self._order(societe=True)
        with self.assertRaises(order_lifecycle.OrderForbidden) as ctx2:
            assignment.claim_order(env, self.livreur, soc_order)
        self.assertIn("reservee a la societe", str(ctx2.exception))
        # platform order before handover → 400
        plain = self._order(shop=self.shop2)
        with self.assertRaises(ValueError):
            assignment.claim_order(env, self.livreur, plain)

    def test_claim_success_bumps_states(self):
        order = self._order(shop=self.shop2)
        assignment.init_handover(self.env, self.shop2, order)
        result = assignment.claim_order(self.env, self.livreur, order)
        self.assertEqual(result["message"], "Mission prise en charge")
        self.assertEqual(result["claim_source"], "plateforme")
        # Reference quirk (LK-SEC-13): run stays ACCEPTED after claim
        self.assertEqual(result["status"], "ACCEPTED")
        run = self.env["likdelivery.delivery.run"].browse(result["delivery_run_id"])
        self.assertEqual(run.livreur_id, self.livreur.partner_id)

    # ----- confirm_cod_payment / validate_delivery -----
    def test_confirm_cod_then_public_validate(self):
        env = self.env
        order = self._order(shop=self.shop2)
        run = assignment.assign_livreur_to_order(
            env, order, self.livreur.partner_id, self.admin
        )
        mission_lifecycle.apply_mission_status(env, run, "STARTED", self.livreur)
        mission_lifecycle.apply_mission_status(env, run, "PICKED_UP", self.livreur)
        # public validate blocked before COD confirm
        with self.assertRaises(ValueError) as ctx:
            assignment.validate_delivery(env, {"otp": run.otp_code})
        self.assertIn("Paiement a la livraison non confirme", str(ctx.exception))
        result = mission_lifecycle.confirm_cod_payment(env, self.livreur, run)
        self.assertIn("Paiement COD confirme", result["message"])
        self.assertEqual(order.payment_status, "paid")
        # now public validation works
        ok = assignment.validate_delivery(env, {"otp": run.otp_code.lower()})
        self.assertEqual(ok["message"], "Livraison validee")
        self.assertEqual(order.state, "DELIVERED")
        self.assertEqual(self.livreur.lik_total_deliveries, 1)

    def test_validate_delivery_qr_and_invalid(self):
        order = self._order(shop=self.shop2, payment="tmoney")
        order.payment_status = "paid"
        run = assignment.assign_livreur_to_order(
            self.env, order, self.livreur.partner_id, self.admin
        )
        result = assignment.validate_delivery(self.env, {"qr_token": run.qr_token})
        self.assertEqual(result["run_id"], run.id)
        with self.assertRaises(ValueError):
            assignment.validate_delivery(self.env, {"otp": "ZZZZZZ"})
