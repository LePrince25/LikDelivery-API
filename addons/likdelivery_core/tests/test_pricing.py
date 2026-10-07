"""Pricing / availability / recommendation unit matrix (S3 acceptance gate).

Every expectation is derived from the Flask reference formulas — these tests
freeze LK-PRC-01..06, LK-HRS-01 and LK-REC-01 against regressions.
"""

from datetime import datetime

from odoo.tests import TransactionCase, tagged

from ..services import availability, pricing, recommendation


@tagged("post_install", "-at_install", "likdelivery")
class TestPricing(TransactionCase):
    def test_haversine_none_is_zero(self):
        self.assertEqual(pricing.haversine(None, 1.0, 2.0, 3.0), 0)
        self.assertEqual(pricing.haversine(6.16, None, 2.0, 3.0), 0)

    def test_haversine_known_distance(self):
        # Lomé market → Adidogome ≈ 6.7 km (reference coordinates)
        km = pricing.haversine(6.1725, 1.2253, 6.16, 1.21)
        self.assertAlmostEqual(km, 2.15, delta=0.3)

    def test_night_window(self):
        self.assertTrue(pricing.is_night_time(datetime(2026, 1, 1, 23, 0)))
        self.assertTrue(pricing.is_night_time(datetime(2026, 1, 1, 5, 59)))
        self.assertFalse(pricing.is_night_time(datetime(2026, 1, 1, 6, 0)))
        self.assertFalse(pricing.is_night_time(datetime(2026, 1, 1, 21, 59)))
        self.assertTrue(pricing.is_night_time(datetime(2026, 1, 1, 22, 0)))

    def test_fee_matrix_day(self):
        """distance 10 km, day: base 3000 / fragile 3600 / hv 4500 / all 7020."""
        self.assertEqual(pricing.calculate_delivery_fee(10.0, night=False), (3000.0, 10.0))
        self.assertEqual(
            pricing.calculate_delivery_fee(10.0, is_fragile=True, night=False),
            (3600.0, 10.0),
        )
        self.assertEqual(
            pricing.calculate_delivery_fee(10.0, high_value=True, night=False),
            (4500.0, 10.0),
        )
        self.assertEqual(
            pricing.calculate_delivery_fee(
                10.0, is_fragile=True, high_value=True, night=True
            ),
            (7020.0, 10.0),
        )

    def test_fee_night_multiplier(self):
        self.assertEqual(
            pricing.calculate_delivery_fee(10.0, night=True), (3900.0, 10.0)
        )

    def test_fee_rounding(self):
        fee, distance = pricing.calculate_delivery_fee(1.234, night=False)
        self.assertEqual(fee, 370.0)  # 370.2 → 370
        self.assertEqual(distance, 1.23)

    def test_high_value_threshold(self):
        self.assertFalse(pricing.is_high_value([50000]))
        self.assertTrue(pricing.is_high_value([50000.01]))
        self.assertTrue(pricing.is_high_value([100, 999999]))

    def test_legacy_fee_fragile_only(self):
        self.assertEqual(pricing.calculate_legacy_fee(10.0), (3000.0, 10.0))
        self.assertEqual(pricing.calculate_legacy_fee(10.0, is_fragile=True), (3600.0, 10.0))

    def test_run_price_fragile_and_night_no_high_value(self):
        self.assertEqual(
            pricing.calculate_run_price(10.0, is_fragile=True, night=True),
            (4680.0, 10.0),
        )

    def test_estimate_breakdown_all_flags(self):
        """Reference incremental order: fragile → night → high_value."""
        b = pricing.estimate_breakdown(10.0, fragile=True, night=True, high_value=True)
        self.assertEqual(b["base"], 3000.0)
        self.assertEqual(b["fragile_bonus"], 600.0)
        self.assertEqual(b["night_bonus"], 1080.0)
        self.assertEqual(b["high_value_bonus"], 2340.0)
        self.assertEqual(b["total"], 7020.0)
        self.assertEqual(b["distance_km"], 10.0)

    def test_estimate_breakdown_no_flags(self):
        b = pricing.estimate_breakdown(5.0)
        self.assertEqual(b, {"distance_km": 5.0, "base": 1500.0, "total": 1500.0})


@tagged("post_install", "-at_install", "likdelivery")
class TestAvailability(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create(
            {"name": "Test Shop", "lik_role": "fournisseur", "lik_validated_by_admin": True}
        )
        cls.Hour = cls.env["likdelivery.opening.hour"]

    def _at(self, weekday, hour, minute=0):
        # 2026-10-05 is a Monday (weekday 0)
        return datetime(2026, 10, 5 + weekday, hour, minute)

    def test_no_hours_means_open(self):
        self.assertTrue(availability.is_open_now(self.partner, at=self._at(0, 3)))

    def test_normal_window(self):
        self.Hour.create(
            {"partner_id": self.partner.id, "day_of_week": "0", "open_time": 6.0, "close_time": 23.0}
        )
        self.assertTrue(availability.is_open_now(self.partner, at=self._at(0, 12)))
        self.assertFalse(availability.is_open_now(self.partner, at=self._at(0, 5)))

    def test_closed_day_when_open_equals_close(self):
        self.Hour.create(
            {"partner_id": self.partner.id, "day_of_week": "1", "open_time": 8.0, "close_time": 8.0}
        )
        self.assertFalse(availability.is_open_now(self.partner, at=self._at(1, 12)))

    def test_overnight_window(self):
        self.Hour.create(
            {"partner_id": self.partner.id, "day_of_week": "2", "open_time": 22.0, "close_time": 6.0}
        )
        self.assertTrue(availability.is_open_now(self.partner, at=self._at(2, 23, 30)))
        self.assertTrue(availability.is_open_now(self.partner, at=self._at(2, 5, 30)))
        self.assertFalse(availability.is_open_now(self.partner, at=self._at(2, 12)))

    def test_float_to_hhmm(self):
        self.assertEqual(availability.float_to_hhmm(6.5), "06:30")
        self.assertEqual(availability.float_to_hhmm(23.0), "23:00")

    def test_supplier_availability_reasons(self):
        ok, reason = availability.supplier_availability(self.partner)
        self.assertTrue(ok)
        self.assertIsNone(reason)
        ghost = self.env["res.partner"]
        self.assertEqual(
            availability.supplier_availability(ghost)[1], "Fournisseur introuvable"
        )
        self.partner.lik_validated_by_admin = False
        ok, reason = availability.supplier_availability(self.partner)
        self.assertFalse(ok)
        self.assertIn("non valide par l'admin", reason)


@tagged("post_install", "-at_install", "likdelivery")
class TestRecommendation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Partner = cls.env["res.partner"]
        cls.liv_low = Partner.create(
            {"name": "Low", "lik_role": "livreur", "lik_average_rating": 3.5, "lik_total_deliveries": 50}
        )
        cls.liv_mid = Partner.create(
            {"name": "Mid", "lik_role": "livreur", "lik_average_rating": 4.2, "lik_total_deliveries": 10}
        )
        cls.liv_high = Partner.create(
            {"name": "High", "lik_role": "livreur", "lik_average_rating": 4.7, "lik_total_deliveries": 5}
        )

    def test_ordering_rating_then_deliveries(self):
        result = recommendation.list_livreurs(self.env)
        ids = [p.id for p in result]
        self.assertLess(ids.index(self.liv_high.id), ids.index(self.liv_mid.id))
        self.assertLess(ids.index(self.liv_mid.id), ids.index(self.liv_low.id))

    def test_min_rating_filter(self):
        result = recommendation.list_livreurs(self.env, min_rating=4.0)
        self.assertNotIn(self.liv_low, result)

    def test_night_threshold(self):
        result = recommendation.recommended_livreurs(self.env, night=True)
        # limit 10: the DB may contain other highly-rated livreurs
        self.assertNotIn(self.liv_low, result)
        self.assertTrue(all(p.lik_average_rating >= 4.0 for p in result))
        self.assertLessEqual(len(result), 10)

    def test_high_value_threshold(self):
        result = recommendation.recommended_livreurs(
            self.env, night=True, high_value=True
        )
        self.assertNotIn(self.liv_mid, result)
        self.assertNotIn(self.liv_low, result)
        self.assertTrue(all(p.lik_average_rating >= 4.5 for p in result))
