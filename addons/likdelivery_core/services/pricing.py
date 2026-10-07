"""Pricing service — exact port of the Flask reference (LK-PRC-01..06).

Constants and formulas are frozen: any change is a business decision, not a
code refactor. Reference: main/app.py lines 39-56, 74-82, 1423-1439.
"""

import math
import os
from datetime import datetime

try:
    from zoneinfo import ZoneInfo

    BUSINESS_TZ = ZoneInfo(os.environ.get("BUSINESS_TZ", "Africa/Lome"))
except Exception:  # pragma: no cover
    BUSINESS_TZ = None

# LK-PRC-01/02 — frozen constants (XOF)
PRICE_PER_KM = 300
FRAGILE_BONUS = 1.2
NIGHT_BONUS = 1.3
HIGH_VALUE_BONUS = 1.5
HIGH_VALUE_THRESHOLD = 50000  # any line unit price > threshold → high value


def haversine(lat1, lon1, lat2, lon2):
    """LK-PRC-05 — exact reference formula, 0 if any coordinate is None."""
    if None in (lat1, lon1, lat2, lon2):
        return 0
    R = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def is_night_time(at=None):
    """LK-PRC-02 — UTC hour < 6 or >= 22 (quirk LK-SEC-03 ported as-is)."""
    hour = (at or datetime.utcnow()).hour
    return hour < 6 or hour >= 22


def now_business():
    """Current naive wall-clock in the business timezone."""
    if BUSINESS_TZ is not None:
        return datetime.now(BUSINESS_TZ).replace(tzinfo=None)
    return datetime.utcnow()


def is_high_value(unit_prices):
    """LK-PRC-02 — any unit price strictly above 50,000 XOF."""
    return any((p or 0) > HIGH_VALUE_THRESHOLD for p in unit_prices)


def calculate_delivery_fee(distance_km, is_fragile=False, high_value=False, night=None):
    """LK-PRC-03 — canonical formula (multi-checkout / checkout-preview).

    fee = distance*300 ×1.2 fragile ×1.5 high_value ×1.3 night
    Returns (fee rounded 0 dp, distance rounded 2 dp).
    """
    fee = distance_km * PRICE_PER_KM
    if is_fragile:
        fee *= FRAGILE_BONUS
    if high_value:
        fee *= HIGH_VALUE_BONUS
    if night is None:
        night = is_night_time()
    if night:
        fee *= NIGHT_BONUS
    return round(fee, 0), round(distance_km, 2)


def calculate_legacy_fee(distance_km, is_fragile=False):
    """LK-PRC-04 — legacy variant (single-order, orders/payment, courier):
    distance*300 ×1.2 fragile only."""
    fee = distance_km * PRICE_PER_KM
    if is_fragile:
        fee *= FRAGILE_BONUS
    return round(fee, 0), round(distance_km, 2)


def calculate_run_price(distance_km, is_fragile=False, night=None):
    """LK-PRC-04 — run price (driver earning): distance*300 ×1.2 fragile
    ×1.3 night (no high-value). Can diverge from the collected delivery fee
    (documented LK-SEC-01)."""
    fee = distance_km * PRICE_PER_KM
    if is_fragile:
        fee *= FRAGILE_BONUS
    if night is None:
        night = is_night_time()
    if night:
        fee *= NIGHT_BONUS
    return round(fee, 0), round(distance_km, 2)


def estimate_breakdown(distance_km, fragile=False, night=False, high_value=False):
    """LK-PRC-06 — /estimate-delivery breakdown.

    Bonus order is fragile → night → high_value, increments computed
    exactly as the reference (multiplicative base, incremental deltas).
    """
    base = distance_km * PRICE_PER_KM
    breakdown = {"distance_km": round(distance_km, 2), "base": round(base, 0)}
    if fragile:
        base *= FRAGILE_BONUS
        breakdown["fragile_bonus"] = round(base - breakdown["base"], 0)
    if night:
        base *= NIGHT_BONUS
        breakdown["night_bonus"] = round(
            base - (breakdown["base"] + breakdown.get("fragile_bonus", 0)), 0
        )
    if high_value:
        base *= HIGH_VALUE_BONUS
        breakdown["high_value_bonus"] = round(
            base
            - sum(
                [
                    breakdown["base"],
                    breakdown.get("fragile_bonus", 0),
                    breakdown.get("night_bonus", 0),
                ]
            ),
            0,
        )
    breakdown["total"] = round(base, 0)
    return breakdown
