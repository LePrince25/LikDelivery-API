"""Order lifecycle + mission engine + BOLA tests (S6 gate).

Covers LK-ORD-02..05, LK-MSN-02..05 and the visibility matrix (can_view_order).
"""

from odoo.tests import TransactionCase, tagged

from ..services import checkout, mission_lifecycle, order_lifecycle


@tagged("post_install", "-at_install", "likdelivery")
class TestOrderLifecycle(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env["res.partner"]

        def mkuser(name, phone, role, **kw):
            partner = Partner.create(
                dict(name=name, phone=phone, lik_role=role, **kw)
            )
            user = cls.env["likdelivery.user"].create(
                {"name": name, "phone": phone, "partner_id": partner.id}
            )
            return user

        cls.client = mkuser("Cli S6", "+22872000001", "client")
        cls.client2 = mkuser("Cli S6b", "+22872000002", "client")
        cls.shop = mkuser(
            "Shop S6", "+22872000003", "fournisseur",
            lik_validated_by_admin=True, lik_company_name="Shop S6",
            partner_latitude=6.1725, partner_longitude=1.2253,
        )
        cls.shop2 = mkuser(
            "Shop S6b", "+22872000004", "fournisseur",
            lik_validated_by_admin=True, lik_company_name="Shop S6b",
        )
        cls.livreur = mkuser("Liv S6", "+22872000005", "livreur")
        cls.livreur2 = mkuser("Liv S6b", "+22872000006", "livreur")
        cls.soc = mkuser(
            "Soc S6", "+22872000007", "societe", lik_validated_by_admin=True
        )
        cls.admin = mkuser("Admin S6", "+22872000008", "admin")
        cls.product = cls.env["likdelivery.product"].create({
            "name": "P S6", "supplier_id": cls.shop.partner_id.id,
            "price": 2000, "stock": 50, "active": True,
        })

    def _order(self, client=None, mode="pickup", payment="cash_on_delivery"):
        client = client or self.client
        data = {
            "supplier_id": self.shop.partner_id.id,
            "mode": mode,
            "payment_method": payment,
            "lines": [{"product_id": self.product.id, "quantity": 2}],
        }
        if mode == "delivery":
            data.update(
                delivery_address="Lome", delivery_lat=6.16, delivery_lon=1.21
            )
        result = checkout.create_legacy_order(self.env, client, data)
        return self.env["likdelivery.order"].browse(result["order_id"])

    def _run(self, order, livreur=None):
        return self.env["likdelivery.run" if False else "likdelivery.delivery.run"].create({
            "order_id": order.id,
            "livreur_id": (livreur or self.livreur).partner_id.id,
            "pickup_address": "Shop", "dropoff_address": "Client",
            "state": "ACCEPTED", "price": 500, "otp_code": "ABC123",
        })

    # ----- can_view_order / BOLA -----
    def test_visibility_matrix(self):
        order = self._order()
        env = self.env
        self.assertTrue(order_lifecycle.can_view_order(env, self.client, order))
        self.assertFalse(order_lifecycle.can_view_order(env, self.client2, order))
        self.assertTrue(order_lifecycle.can_view_order(env, self.shop, order))
        self.assertFalse(order_lifecycle.can_view_order(env, self.shop2, order))
        self.assertTrue(order_lifecycle.can_view_order(env, self.admin, order))
        self.assertFalse(order_lifecycle.can_view_order(env, self.livreur, order))
        self._run(order)
        self.assertTrue(order_lifecycle.can_view_order(env, self.livreur, order))
        self.assertFalse(order_lifecycle.can_view_order(env, self.livreur2, order))

    def test_societe_visibility(self):
        order = self._order(mode="delivery")
        order.preferred_societe_id = self.soc.partner_id
        self.assertTrue(order_lifecycle.can_view_order(self.env, self.soc, order))
        self.assertFalse(order_lifecycle.can_view_order(self.env, self.livreur, order))

    def test_list_scoping(self):
        o1 = self._order(client=self.client)
        o2 = self._order(client=self.client2)
        env = self.env
        client_ids = [o["id"] for o in order_lifecycle.list_orders_for(env, self.client)]
        self.assertIn(o1.id, client_ids)
        self.assertNotIn(o2.id, client_ids)
        shop_ids = [o["id"] for o in order_lifecycle.list_orders_for(env, self.shop)]
        self.assertIn(o1.id, shop_ids)
        self.assertIn(o2.id, shop_ids)
        admin_ids = [o["id"] for o in order_lifecycle.list_orders_for(env, self.admin)]
        self.assertIn(o1.id, admin_ids)
        self.assertIn(o2.id, admin_ids)

    # ----- order_to_dict flags -----
    def test_order_to_dict_handover_flags(self):
        order = self._order(mode="delivery")
        d = order_lifecycle.order_to_dict(self.env, order, detailed=True)
        self.assertEqual(d["status"], "CREATED")
        self.assertTrue(d["payment_ready"])  # COD
        self.assertFalse(d["has_shop_livreurs"])
        self.assertEqual(d["handover_for"], "a_definir")
        self.assertTrue(d["can_init_handover"])
        self.assertFalse(d["can_assign_shop_livreur"])
        self.assertIsNotNone(d["otp"])  # detailed
        self.assertEqual(len(d["lines"]), 1)
        d_public = order_lifecycle.order_to_dict(self.env, order)
        self.assertIsNone(d_public["otp"])  # not detailed

    def test_handover_for_pickup_and_assigned(self):
        order = self._order(mode="pickup")
        d = order_lifecycle.order_to_dict(self.env, order)
        self.assertEqual(d["handover_for"], "client")
        order2 = self._order(mode="delivery")
        self._run(order2)
        d2 = order_lifecycle.order_to_dict(self.env, order2)
        self.assertEqual(d2["handover_for"], "livreur")

    # ----- supplier status -----
    def test_update_order_status(self):
        order = self._order()
        order_lifecycle.update_order_status(
            self.env, self.shop, order, "PREPARING"
        )
        self.assertEqual(order.state, "PREPARING")
        notif = self.env["likdelivery.notification"].search(
            [("user_id", "=", self.client.partner_id.id)], order="id desc", limit=1
        )
        self.assertIn("PREPARING", notif.body)

    def test_update_order_status_delivered_credits_supplier(self):
        order = self._order()
        order_lifecycle.update_order_status(self.env, self.shop, order, "DELIVERED")
        self.assertTrue(order.supplier_wallet_credited)
        # idempotent: second DELIVERED does not raise
        order_lifecycle.update_order_status(self.env, self.admin, order, "DELIVERED")

    def test_update_order_status_forbidden_and_invalid(self):
        order = self._order()
        with self.assertRaises(order_lifecycle.OrderForbidden):
            order_lifecycle.update_order_status(self.env, self.shop2, order, "PREPARING")
        with self.assertRaises(ValueError):
            order_lifecycle.update_order_status(self.env, self.shop, order, "BOGUS")

    # ----- pickup actions (self-pickup) -----
    def test_pickup_init_and_confirm(self):
        order = self._order(mode="pickup")
        result = order_lifecycle.pickup_action(
            self.env, self.client, order, "init_pickup"
        )
        self.assertEqual(order.state, "PICKUP_IN_PROGRESS")
        self.assertEqual(result["_audit"], "INIT_PICKUP")
        result = order_lifecycle.pickup_action(
            self.env, self.client, order, "confirm_received"
        )
        self.assertEqual(order.state, "DELIVERED")
        self.assertTrue(order.supplier_wallet_credited)
        self.assertEqual(result["_audit"], "CONFIRM_PICKUP_RECEIVED")

    def test_pickup_confirm_quirk_any_status(self):
        """Reference quirk: confirm_received works from any status."""
        order = self._order(mode="pickup")
        order_lifecycle.pickup_action(self.env, self.client, order, "confirm_received")
        self.assertEqual(order.state, "DELIVERED")

    def test_pickup_action_forbidden(self):
        order = self._order(mode="pickup")
        with self.assertRaises(order_lifecycle.OrderForbidden):
            order_lifecycle.pickup_action(self.env, self.client2, order, "init_pickup")
        with self.assertRaises(ValueError):
            order_lifecycle.pickup_action(self.env, self.client, order, "fly")

    # ----- mission engine -----
    def test_mission_transition_validation(self):
        order = self._order(mode="delivery")
        run = self._run(order)
        with self.assertRaises(ValueError) as ctx:
            mission_lifecycle.apply_mission_status(
                self.env, run, "DELIVERED", self.livreur, otp="ABC123"
            )
        self.assertIn("Transition invalide", str(ctx.exception))

    def test_mission_full_chain_with_cod(self):
        order = self._order(mode="delivery", payment="cash_on_delivery")
        run = self._run(order)
        env = self.env
        mission_lifecycle.apply_mission_status(env, run, "STARTED", self.livreur)
        self.assertEqual(order.state, "PICKUP_IN_PROGRESS")
        mission_lifecycle.apply_mission_status(env, run, "PICKUP_INITIATED", self.livreur)
        mission_lifecycle.apply_mission_status(env, run, "PICKED_UP", self.livreur)
        self.assertEqual(order.state, "OUT_FOR_DELIVERY")
        self.assertIsNotNone(run.pickup_time)
        mission_lifecycle.apply_mission_status(env, run, "IN_TRANSIT", self.livreur)
        # COD not confirmed → DELIVERED refused
        with self.assertRaises(ValueError) as ctx:
            mission_lifecycle.apply_mission_status(
                env, run, "DELIVERED", self.livreur, otp="ABC123"
            )
        self.assertIn("Paiement a la livraison non confirme", str(ctx.exception))
        # wrong OTP refused after payment confirmed
        order.payment_status = "paid"
        with self.assertRaises(ValueError):
            mission_lifecycle.apply_mission_status(
                env, run, "DELIVERED", self.livreur, otp="WRONG1"
            )
        # correct OTP (case-insensitive) → delivered + credits
        mission_lifecycle.apply_mission_status(
            env, run, "DELIVERED", self.livreur, otp="abc123"
        )
        self.assertEqual(order.state, "DELIVERED")
        self.assertIsNotNone(run.delivery_time)
        self.assertTrue(order.supplier_wallet_credited)
        self.assertEqual(self.livreur.lik_total_deliveries, 1)
        notifs = self.env["likdelivery.notification"].search(
            [("user_id", "=", self.client.partner_id.id), ("title", "=", "Suivi livraison")]
        )
        self.assertTrue(len(notifs) >= 4)

    def test_mission_dict_flags(self):
        order = self._order(mode="delivery")
        run = self._run(order)
        d = mission_lifecycle.mission_dict(self.env, run)
        self.assertEqual(d["status_label"], "Acceptee — a demarrer")
        self.assertTrue(d["can_start"])
        self.assertEqual(d["next_action"]["action"], "start")
        self.assertEqual(d["order_code"], order.code)
        self.assertEqual(d["price"], 500)
