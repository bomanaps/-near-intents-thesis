from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import product
from typing import Optional

from .issuance import (
    IssuanceParams,
    RevenueParams,
    compute,
    find_break_even_date,
    project_hsp029_ramp,
)

SUPPLY_NEAR = Decimal("1309640572.78")
NEAR_PRICE_USD = Decimal("4.37")

VOLUME_FLAT_30D_USD = Decimal("127280000")
VOLUME_FLAT_90D_USD = Decimal("127590000")
VOLUME_BEST_30D_USD = Decimal("161190000")

CAPTURE_RATE_DEFI_LLAMA_30D = Decimal("0.000591")
CAPTURE_RATE_NEAR_KEEPS_ALLINFEE = Decimal("0.000411")

ISSUANCE_CAP_CURRENT = Decimal("0.025")
ISSUANCE_CAP_HSP029_FLOOR = Decimal("0.016")

HSP029_ACTIVATION_DATE = date(2026, 11, 2)


@dataclass(frozen=True)
class ScenarioInput:
    label: str
    issuance_label: str
    annual_cap: Decimal
    volume_label: str
    volume_usd_per_day: Decimal
    capture_label: str
    capture_rate: Decimal
    buyback_label: str


@dataclass
class ScenarioResult:
    label: str
    issuance_label: str
    volume_label: str
    capture_label: str
    buyback_label: str
    near_issued_per_day: Decimal
    issuance_usd_per_day: Decimal
    near_bought_per_day: Decimal
    buyback_usd_per_day: Decimal
    offset_ratio: Decimal
    break_even_volume_usd: Decimal
    break_even_date: Optional[date]
    times_current_volume: Decimal


_ISSUANCE_SCENARIOS = [
    ("2.5% flat (today)", ISSUANCE_CAP_CURRENT),
    ("1.6% floor (HSP-029 end state)", ISSUANCE_CAP_HSP029_FLOOR),
]

_VOLUME_SCENARIOS = [
    ("trailing 30d avg ($127M/day)", VOLUME_FLAT_30D_USD),
    ("trailing 90d avg ($128M/day)", VOLUME_FLAT_90D_USD),
    ("best 30d pace ($161M/day)", VOLUME_BEST_30D_USD),
]

_CAPTURE_SCENARIOS = [
    ("5.91 bps (DefiLlama 30d revenue/volume)", CAPTURE_RATE_DEFI_LLAMA_30D),
    ("4.11 bps (90d trailing revenue/volume)", CAPTURE_RATE_NEAR_KEEPS_ALLINFEE),
]

_BUYBACK_SCENARIOS = [
    "held in wallets (as today)",
    "burned",
]


def run_all() -> list[ScenarioResult]:
    results = []

    for (iso_label, cap), (vol_label, vol), (cap_label, capture), buyback_label in product(
        _ISSUANCE_SCENARIOS,
        _VOLUME_SCENARIOS,
        _CAPTURE_SCENARIOS,
        _BUYBACK_SCENARIOS,
    ):
        issuance = IssuanceParams(
            total_supply_near=SUPPLY_NEAR,
            annual_cap=cap,
            near_price_usd=NEAR_PRICE_USD,
        )
        revenue = RevenueParams(
            volume_usd_per_day=vol,
            capture_rate=capture,
        )
        daily = compute(issuance, revenue)

        projected = project_hsp029_ramp(
            activation_date=HSP029_ACTIVATION_DATE,
            total_supply_near=SUPPLY_NEAR,
            near_price_usd=NEAR_PRICE_USD,
            capture_rate=capture,
            volume_usd_per_day=vol,
        )
        be_date = find_break_even_date(projected)

        times_current = (
            daily.break_even_volume_usd / vol
            if vol > 0
            else Decimal(0)
        )

        label = f"{iso_label} | {vol_label} | {cap_label} | {buyback_label}"

        results.append(
            ScenarioResult(
                label=label,
                issuance_label=iso_label,
                volume_label=vol_label,
                capture_label=cap_label,
                buyback_label=buyback_label,
                near_issued_per_day=daily.near_issued_per_day,
                issuance_usd_per_day=daily.issuance_usd_per_day,
                near_bought_per_day=daily.near_bought_per_day,
                buyback_usd_per_day=daily.buyback_usd_per_day,
                offset_ratio=daily.offset_ratio,
                break_even_volume_usd=daily.break_even_volume_usd,
                break_even_date=be_date,
                times_current_volume=times_current,
            )
        )

    return results


if __name__ == "__main__":
    results = run_all()
    header = (
        f"{'Issuance':<35} {'Capture':<45} {'Issued/day':>12} "
        f"{'Offset':>8} {'BEV ($M)':>10} {'×Today':>8} {'BE Date'}"
    )
    print(header)
    print("-" * len(header))
    seen = set()
    for r in results:
        key = (r.issuance_label, r.capture_label)
        if key in seen:
            continue
        seen.add(key)
        bev_m = r.break_even_volume_usd / Decimal("1000000")
        be_date = str(r.break_even_date) if r.break_even_date else "never (3yr)"
        print(
            f"{r.issuance_label:<35} {r.capture_label:<45} "
            f"{float(r.near_issued_per_day):>12,.0f} "
            f"{float(r.offset_ratio):>8.1%} "
            f"{float(bev_m):>10,.0f} "
            f"{float(r.times_current_volume):>8.1f}x "
            f"{be_date}"
        )
