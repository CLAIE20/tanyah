from typing import Optional

# Pricing tuned for local urban deliveries and displayed alongside the
# latest confirmed RBZ interbank conversion rate.
BASE_DELIVERY_FEE_USD = 2.00
PER_KM_DELIVERY_FEE_USD = 0.85
MINIMUM_DELIVERY_FEE_USD = 3.50

USD_TO_ZIG_RATE = 25.1937
RBZ_RATE_EFFECTIVE_DATE = "2026-04-27"


def round_money(amount: float) -> float:
    return round(amount, 2)


def calculate_delivery_fee(distance_km: Optional[float]) -> float:
    safe_distance = max(distance_km or 0.0, 0.0)
    raw_total = BASE_DELIVERY_FEE_USD + (safe_distance * PER_KM_DELIVERY_FEE_USD)
    return round_money(max(raw_total, MINIMUM_DELIVERY_FEE_USD))


def convert_usd_to_zig(amount_usd: float) -> float:
    return round_money(max(amount_usd, 0.0) * USD_TO_ZIG_RATE)
