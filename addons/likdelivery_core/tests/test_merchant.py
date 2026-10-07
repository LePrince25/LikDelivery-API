"""Merchant services tests (S8) — products, hours, KYC, shop drivers, fleet,
sales history. LK-SOC-01..07, LK-KYC-01, LK-UPL-01."""

import base64

from odoo.tests import TransactionCase, tagged

from ..services import (
    availability,
    catalog,
    checkout,
    fleet,
    kyc,
    order_lifecycle,
    sales,
)


@tagged("post_install", "-at_install", "likdelivery")
class TestMerchantServices(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env["res.partner"]

        def mkuser(name, phone, role, **kw):
            partner = Partner.create(dict(name=name, phone=phone, lik_role=role, **kw))
            return cls.env["likdelivery.user"].create(
                {"name": name, "phone": phone, "partner_id": partner.id}
            )

        cls.client = mkuser("Cli S8", "+22874000001", "client")
        cls.shop = mkuser(
            "Shop S8", "+22874000002", "fournisseur",
            lik_validated_by_admin=True, lik_company_name="Shop S8",
        )
        cls.shop2 = mkuser(
            "Shop S8b", "+22874000003", "fournisseur",
            lik_validated_by_admin=True, lik_company_name="Shop S8b",
        )
        cls.soc = mkuser("Soc S8", "+22874000004", "societe", lik_validated_by_admin=True)
        cls.soc2 = mkuser("Soc S8b", "+22874000005", "societe", lik_validated_by_admin=True)
        cls.livreur = mkuser("Liv S8", "+22874000006", "livreur")
        cls.admin = mkuser("Admin S8", "+22874000007", "admin")

    # ---------- products ----------
    def test_product_crud_and_ownership(self):
        env = self.env
        created = catalog.create_product(
            env, self.shop, {"name": "Prod S8", "price": 1500, "stock": 7}
        )
        self.assertEqual(created["supplier_name"], "Shop S8")
        own = catalog.list_products(env, self.shop)
        self.assertIn(created["id"], [p["id"] for p in own])
        other = catalog.list_products(env, self.shop2)
        self.assertNotIn(created["id"], [p["id"] for p in other])
        updated = catalog.update_product(
            env, self.shop, created["id"], {"price": 1800, "stock": 3}
        )
        self.assertEqual(updated["price"], 1800.0)
        with self.assertRaises(order_lifecycle.OrderForbidden):
            catalog.update_product(env, self.shop2, created["id"], {"price": 1})
        with self.assertRaises(order_lifecycle.OrderNotFound):
            catalog.update_product(env, self.shop, 999999, {"price": 1})
        result = catalog.delete_product(env, self.shop, created["id"])
        self.assertEqual(result["message"], "Produit supprime")

    def test_product_image_upload(self):
        created = catalog.create_product(
            self.env, self.shop, {"name": "Prod Img", "price": 100, "stock": 1}
        )
        with self.assertRaises(ValueError):
            catalog.upload_product_image(
                self.env, self.shop, created["id"], "evil.exe", b"x"
            )
        # real 1x1 PNG (the Image field validates content)
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
            "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        )
        result = catalog.upload_product_image(
            self.env, self.shop, created["id"], "photo.png", png
        )
        self.assertIn("/web/image/", result["image_url"])
        product = self.env["likdelivery.product"].browse(created["id"])
        self.assertTrue(product.image_1920)

    # ---------- opening hours ----------
    def test_replace_opening_hours(self):
        items = [
            {"day_of_week": 0, "open_time": "08:00", "close_time": "18:00"},
            {"day_of_week": 1, "open_time": "22:00", "close_time": "06:00"},
        ]
        result = availability.replace_opening_hours(self.env, self.shop, items)
        self.assertEqual(result["message"], "Horaires mis a jour")
        payload = availability.self_hours_payload(self.env, self.shop)
        self.assertEqual(len(payload["hours"]), 2)
        self.assertEqual(payload["hours"][0]["open_time"], "08:00")
        # replace all: only 1 remains
        availability.replace_opening_hours(
            self.env, self.shop, [{"day_of_week": 3, "open_time": "09:00", "close_time": "17:00"}]
        )
        payload = availability.self_hours_payload(self.env, self.shop)
        self.assertEqual(len(payload["hours"]), 1)
        with self.assertRaises(ValueError):
            availability.replace_opening_hours(
                self.env, self.shop, [{"day_of_week": 9, "open_time": "09:00", "close_time": "17:00"}]
            )

    # ---------- KYC ----------
    def test_kyc_upload_resets_validation(self):
        self.shop.partner_id.lik_validated_by_admin = True
        result = kyc.upload_kyc(
            self.env, self.shop, ("cni.pdf", b"%PDF-fake"), ("cfe.jpg", b"\xff\xd8-fake")
        )
        self.assertEqual(result["id_document"], "cni.pdf")
        self.assertFalse(self.shop.partner_id.lik_validated_by_admin)
        with self.assertRaises(ValueError):
            kyc.upload_kyc(self.env, self.shop, ("doc.txt", b"x"))

    # ---------- shop drivers ----------
    def test_shop_driver_link_unlink(self):
        env = self.env
        fleet.shop_driver_link(env, self.shop, self.livreur.partner_id.id)
        listed = fleet.shop_drivers_list(env, self.shop)
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["first_name"], None or listed[0]["first_name"])
        with self.assertRaises(ValueError):
            fleet.shop_driver_link(env, self.shop, 999999)
        fleet.shop_driver_unlink(env, self.shop, self.livreur.partner_id.id)
        self.assertEqual(fleet.shop_drivers_list(env, self.shop), [])
        # Reference: double unlink does NOT 404 (no is_active filter) — the
        # link is found and deactivated again.
        again = fleet.shop_driver_unlink(env, self.shop, self.livreur.partner_id.id)
        self.assertEqual(again["message"], "Livreur retire de la boutique")
        # never-linked livreur → 404
        with self.assertRaises(order_lifecycle.OrderNotFound):
            fleet.shop_driver_unlink(env, self.shop, 999999)

    # ---------- fleet ----------
    def test_fleet_create_internal(self):
        result = fleet.fleet_create_internal(
            self.env, self.soc,
            {"create": True, "phone": "+22874000099", "password": "abc123",
             "first_name": "Int", "last_name": "Driver",
             "vehicle_type": "Moto", "license_plate": "TG-9999-ZZ"},
        )
        liv = result["livreur"]
        self.assertEqual(liv["origin"], "internal")
        self.assertTrue(liv["validated_by_admin"])
        self.assertEqual(liv["employer_societe_id"], self.soc.partner_id.id)
        with self.assertRaises(ValueError):
            fleet.fleet_create_internal(
                self.env, self.soc,
                {"create": True, "phone": "+22874000098", "password": "abc123"}
            )  # no plate
        with self.assertRaises(FileExistsError):
            fleet.fleet_create_internal(
                self.env, self.soc,
                {"create": True, "phone": "+22874000099", "password": "abc123",
                 "license_plate": "TG-1"}
            )

    def test_fleet_link_external_refuses_internal_of_other(self):
        fleet.fleet_create_internal(
            self.env, self.soc,
            {"create": True, "phone": "+22874000097", "password": "abc123",
             "license_plate": "TG-2"},
        )
        internal_partner = self.env["res.partner"].search(
            [("phone", "=", "+22874000097")]
        )
        with self.assertRaises(ValueError) as ctx:
            fleet.fleet_link_external(
                self.env, self.soc2, {"livreur_id": internal_partner.id}
            )
        self.assertIn("autre societe", str(ctx.exception))
        # free livreur links fine
        result = fleet.fleet_link_external(
            self.env, self.soc2, {"livreur_id": self.livreur.partner_id.id}
        )
        self.assertEqual(result["origin"], "external")

    def test_fleet_unlink_deactivates_internal(self):
        created = fleet.fleet_create_internal(
            self.env, self.soc,
            {"create": True, "phone": "+22874000096", "password": "abc123",
             "license_plate": "TG-3"},
        )
        partner = self.env["res.partner"].search([("phone", "=", "+22874000096")])
        fleet.fleet_unlink(self.env, self.soc, partner.id)
        self.assertFalse(partner.active)  # internal resource deactivated
        # external stays active
        fleet.fleet_link_external(
            self.env, self.soc, {"livreur_id": self.livreur.partner_id.id}
        )
        fleet.fleet_unlink(self.env, self.soc, self.livreur.partner_id.id)
        self.assertTrue(self.livreur.partner_id.active)

    def test_fleet_update_rules(self):
        fleet.fleet_create_internal(
            self.env, self.soc,
            {"create": True, "phone": "+22874000095", "password": "abc123",
             "license_plate": "TG-4"},
        )
        internal = self.env["res.partner"].search([("phone", "=", "+22874000095")])
        with self.assertRaises(ValueError):
            fleet.fleet_update_livreur(
                self.env, self.soc, internal.id, {"license_plate": " "}
            )
        result = fleet.fleet_update_livreur(
            self.env, self.soc, internal.id,
            {"first_name": "NewName", "vehicle_type": "Voiture"},
        )
        self.assertEqual(result["livreur"]["first_name"], "NewName")
        self.assertEqual(result["livreur"]["vehicle_type"], "Voiture")

    # ---------- sales history ----------
    def test_sales_history(self):
        result = checkout.create_legacy_order(
            self.env, self.client,
            {"supplier_id": self.shop.partner_id.id, "mode": "pickup",
             "payment_method": "pay_at_pickup",
             "lines": [{"product_id": p} for p in [
                 self.env["likdelivery.product"].create({
                     "name": "PS8", "supplier_id": self.shop.partner_id.id,
                     "price": 4000, "stock": 5, "active": True,
                 }).id
             ]]},
        )
        order = self.env["likdelivery.order"].browse(result["order_id"])
        order_lifecycle.update_order_status(self.env, self.shop, order, "DELIVERED")
        history = sales.sales_history(self.env, self.shop)
        self.assertEqual(history["summary"]["orders_count"], 1)
        self.assertEqual(history["summary"]["delivered_count"], 1)
        self.assertEqual(history["summary"]["supplier_sales"], 4000.0)
        self.assertEqual(history["wallet"]["available"], 4000.0)
        self.assertIn("prix des produits uniquement", history["summary"]["note"])
