from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class IssuanceParams:
    total_supply_near: Decimal
    annual_cap: Decimal
    near_price_usd: Decimal


@dataclass(frozen=True)
class RevenueParams:
    volume_usd_per_day: Decimal
    capture_rate: Decimal


@dataclass(frozen=True)
class DailyResult:
    near_issued_per_day: Decimal
    issuance_usd_per_day: Decimal
    near_bought_per_day: Decimal
    buyback_usd_per_day: Decimal
    offset_ratio: Decimal
    break_even_volume_usd: Decimal


def _cap_hsp029(months_since_activation: int) -> Decimal:
    t = min(months_since_activation, 24)
    return Decimal("0.025") - Decimal("0.009") * Decimal(t) / Decimal(24)


def near_issued_per_day(
    total_supply_near: Decimal,
    annual_cap: Decimal,
) -> Decimal:
    return total_supply_near * annual_cap / Decimal(365)


def near_bought_per_day(
    volume_usd_per_day: Decimal,
    capture_rate: Decimal,
    near_price_usd: Decimal,
) -> Decimal:
    return volume_usd_per_day * capture_rate / near_price_usd


def offset_ratio(
    near_bought: Decimal,
    near_issued: Decimal,
) -> Decimal:
    if near_issued == 0:
        return Decimal(0)
    return near_bought / near_issued


def break_even_volume_usd(
    near_issued: Decimal,
    near_price_usd: Decimal,
    capture_rate: Decimal,
) -> Decimal:
    if capture_rate == 0:
        return Decimal("Infinity")
    return near_issued * near_price_usd / capture_rate


def compute(
    issuance: IssuanceParams,
    revenue: RevenueParams,
) -> DailyResult:
    issued = near_issued_per_day(issuance.total_supply_near, issuance.annual_cap)
    bought = near_bought_per_day(
        revenue.volume_usd_per_day,
        revenue.capture_rate,
        issuance.near_price_usd,
    )
    ratio = offset_ratio(bought, issued)
    bev = break_even_volume_usd(issued, issuance.near_price_usd, revenue.capture_rate)

    return DailyResult(
        near_issued_per_day=issued,
        issuance_usd_per_day=issued * issuance.near_price_usd,
        near_bought_per_day=bought,
        buyback_usd_per_day=bought * issuance.near_price_usd,
        offset_ratio=ratio,
        break_even_volume_usd=bev,
    )


def project_hsp029_ramp(
    activation_date: date,
    total_supply_near: Decimal,
    near_price_usd: Decimal,
    capture_rate: Decimal,
    volume_usd_per_day: Decimal,
    days: int = 365 * 3,
) -> list[tuple[date, DailyResult]]:
    results = []
    for i in range(days):
        d = activation_date + timedelta(days=i)
        months_elapsed = (
            (d.year - activation_date.year) * 12
            + (d.month - activation_date.month)
        )
        cap = _cap_hsp029(months_elapsed)
        issuance = IssuanceParams(
            total_supply_near=total_supply_near,
            annual_cap=cap,
            near_price_usd=near_price_usd,
        )
        revenue = RevenueParams(
            volume_usd_per_day=volume_usd_per_day,
            capture_rate=capture_rate,
        )
        results.append((d, compute(issuance, revenue)))
    return results


def find_break_even_date(
    projected: list[tuple[date, DailyResult]],
) -> Optional[date]:
    for d, result in projected:
        if result.offset_ratio >= 1:
            return d
    return None
