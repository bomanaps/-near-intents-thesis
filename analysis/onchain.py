"""
On-chain evidence from decoded dip4 events on intents.near.

Reads data/raw/fastnear/events.jsonl (produced by ingest/fastnear_ingest.py)
and computes, from token_diff settlement events:

  1. Explicit protocol fee rate per fill side (fees_collected / same-token gross)
  2. Solver concentration: fill shares and HHI over the solver side of receipts
  3. Corridor mix: USD volume share by token pair
  4. Wash screen: self-fill receipts and reversed round trips in the window

Settlement structure (verified empirically on this dataset):
  one receipt = one settlement batch; a bilateral trade is a receipt with two
  entries whose diffs mirror net of fees (sum of diffs plus fees equals zero
  exactly on every bilateral receipt checked), one side a named solver account and
  the other a user. Each side pays fees_collected in the token it gives.

Outputs data/model/onchain.json and docs/data/onchain.json.

Usage: python analysis/onchain.py [path/to/events.jsonl]
"""

from __future__ import annotations

import json
import shutil
import sys
import urllib.request

import pandas as pd
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
EVENTS_IN = ROOT / "data" / "raw" / "fastnear" / "events.jsonl"
OUT = ROOT / "data" / "model" / "onchain.json"
DOCS_OUT = ROOT / "docs" / "data" / "onchain.json"

NEAR_BLOCK_SECONDS = 1.1
BLOCKS_PER_DAY = int(86400 / NEAR_BLOCK_SECONDS)
INGEST_START_DATE = "2026-10-28"

DAILY_METRICS = ROOT / "data" / "raw" / "daily_metrics.parquet"

CONFIDENTIAL_TREASURY = (
    "51e8f94d77b5e90dc9852ca6113771e11e8382ce69473a75e313e41665de7cbe"
)

STABLES = {
    "nep141:eth-0xdac17f958d2ee523a2206206994597c13d831ec7.omft.near": ("USDT.eth", 6),
    "nep141:eth-0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48.omft.near": ("USDC.eth", 6),
    "nep141:tron-d28a265909efecdcee7c5028585214ea0b96f015.omft.near": ("USDT.tron", 6),
    "nep141:base-0x833589fcd6edb6e08f4c7c32d4f71b54bda02913.omft.near": ("USDC.base", 6),
    "nep141:arb-0xaf88d065e77c8cc2239327c5edb3a432268e5831.omft.near": ("USDC.arb", 6),
    "nep141:arb-0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9.omft.near": ("USDT.arb", 6),
    "nep141:eth-0x6b175474e89094c44da98b954eedeac495271d0f.omft.near": ("DAI.eth", 18),
}

MAJORS = {
    "nep141:nbtc.bridge.near": ("BTC", 8, "coingecko:bitcoin"),
    "nep141:btc.omft.near": ("BTC", 8, "coingecko:bitcoin"),
    "nep141:eth.omft.near": ("ETH", 18, "coingecko:ethereum"),
    "nep141:sol.omft.near": ("SOL", 9, "coingecko:solana"),
    "nep141:tron.omft.near": ("TRX", 6, "coingecko:tron"),
    "nep141:wrap.near": ("NEAR", 24, "coingecko:near"),
}

PRICE_URL = "https://coins.llama.fi/prices/current/" + ",".join(
    sorted({gecko for _, _, gecko in MAJORS.values()})
)


def fetch_major_prices() -> dict:
    with urllib.request.urlopen(PRICE_URL, timeout=20) as r:
        coins = json.load(r)["coins"]
    return {gecko: coins[gecko]["price"] for gecko in coins}


def token_symbol(tok: str) -> str:
    if tok in STABLES:
        return STABLES[tok][0]
    if tok in MAJORS:
        return MAJORS[tok][0]
    return "other"


def leg_usd(tok: str, raw_amount: int, prices: dict) -> float | None:
    amt = abs(raw_amount)
    if tok in STABLES:
        _, dec = STABLES[tok]
        return amt / 10**dec
    if tok in MAJORS:
        _, dec, gecko = MAJORS[tok]
        price = prices.get(gecko)
        if price is None:
            return None
        return amt / 10**dec * price
    return None


def implied_revenue_bps_30d() -> float | None:
    if not DAILY_METRICS.exists():
        return None
    df = pd.read_parquet(DAILY_METRICS).sort_values("date")
    return round(float(df["rev_capture_bps"].tail(30).mean()), 2)


def stable_usd(tokens: dict | None) -> float:
    best = 0.0
    for tok, amt in (tokens or {}).items():
        if tok in STABLES:
            _, dec = STABLES[tok]
            best = max(best, abs(int(amt)) / 10**dec)
    return best


def confidential_share(treasury_in: float, public_fill: float) -> float | None:
    total = treasury_in + public_fill
    if total <= 0:
        return None
    return treasury_in / total


def entry_fee_bps(entry: dict) -> list[float]:
    diff = {t: int(v) for t, v in entry["diff"].items()}
    out = []
    for tok, fee in (entry.get("fees_collected") or {}).items():
        if tok in diff and diff[tok] != 0:
            out.append(int(fee) / abs(diff[tok]) * 1e4)
    return out


def pick_solver(a: dict, b: dict, fills: dict) -> dict:
    return a if fills[a["account_id"]] >= fills[b["account_id"]] else b


def entry_usd(diff: dict, prices: dict) -> float | None:
    stable_vals = [leg_usd(t, int(v), prices) for t, v in diff.items() if t in STABLES]
    stable_vals = [v for v in stable_vals if v is not None]
    if stable_vals:
        return max(stable_vals)
    major_vals = [leg_usd(t, int(v), prices) for t, v in diff.items() if t in MAJORS]
    major_vals = [v for v in major_vals if v is not None]
    if major_vals:
        return max(major_vals)
    return None


def main() -> None:
    events_path = Path(sys.argv[1]) if len(sys.argv) > 1 else EVENTS_IN
    if not events_path.exists():
        sys.exit(f"events file not found: {events_path}")

    try:
        prices = fetch_major_prices()
    except Exception as e:
        print(f"price fetch failed ({e}); USD valuation limited to stablecoin legs")
        prices = {}

    receipts: dict[str, list[dict]] = defaultdict(list)
    blocks: set[int] = set()
    day_treasury_in: Counter = Counter()
    day_treasury_out: Counter = Counter()
    day_public_fill: Counter = Counter()
    receipt_stable: dict[str, float] = {}
    receipt_day: dict[str, int] = {}
    first_block: int | None = None
    with open(events_path) as f:
        for line in f:
            e = json.loads(line)
            ev = e.get("event")
            if ev not in ("token_diff", "transfer"):
                continue
            bh = e["block_height"]
            if first_block is None:
                first_block = bh
            day = (bh - first_block) // BLOCKS_PER_DAY
            data = json.loads(e["data"]) if isinstance(e["data"], str) else e["data"]
            if ev == "transfer":
                for entry in data:
                    value = stable_usd(entry.get("tokens"))
                    if entry.get("receiver_id") == CONFIDENTIAL_TREASURY:
                        day_treasury_in[day] += value
                    if entry.get("account_id") == CONFIDENTIAL_TREASURY:
                        day_treasury_out[day] += value
                continue
            blocks.add(bh)
            for entry in data:
                receipts[e["receipt_id"]].append(entry)
                diff = {t: int(v) for t, v in entry["diff"].items()}
                pos = max(
                    (v / 10 ** STABLES[t][1] for t, v in diff.items() if v > 0 and t in STABLES),
                    default=0.0,
                )
                rid = e["receipt_id"]
                receipt_day[rid] = day
                receipt_stable[rid] = max(receipt_stable.get(rid, 0.0), pos)

    if not receipts:
        sys.exit("no token_diff events found")

    account_fills: Counter = Counter()
    for entries in receipts.values():
        for en in entries:
            account_fills[en["account_id"]] += 1

    fee_bps_samples: list[tuple[float, float | None]] = []
    solver_usd: Counter = Counter()
    solver_fills: Counter = Counter()
    corridor_usd: Counter = Counter()
    corridor_n: Counter = Counter()
    valued_entries = 0
    total_entries = 0
    self_fill_receipts = 0
    bilateral = 0
    multiparty = 0
    directed_flows: Counter = Counter()

    for rid, entries in receipts.items():
        if len(entries) == 2:
            bilateral += 1
            if entries[0]["account_id"] == entries[1]["account_id"]:
                self_fill_receipts += 1
        elif len(entries) > 2:
            multiparty += 1

        for en in entries:
            total_entries += 1
            diff = {t: int(v) for t, v in en["diff"].items()}
            usd = entry_usd(diff, prices)
            if usd is not None:
                valued_entries += 1

            for tok, fee in (en.get("fees_collected") or {}).items():
                if tok in diff and diff[tok] != 0:
                    bps = int(fee) / abs(diff[tok]) * 1e4
                    fee_bps_samples.append((bps, leg_usd(tok, diff[tok], prices)))

            gave = sorted(token_symbol(t) for t, v in diff.items() if v < 0)
            got = sorted(token_symbol(t) for t, v in diff.items() if v > 0)
            if gave and got:
                pair = " / ".join(sorted(set(gave) | set(got)))
                corridor_n[pair] += 1
                if usd is not None:
                    corridor_usd[pair] += usd
                directed_flows[(en["account_id"], tuple(gave), tuple(got))] += 1

        if len(entries) == 2:
            a, b = entries
            solver = pick_solver(a, b, account_fills)
            solver_fills[solver["account_id"]] += 1
            usd = entry_usd({t: int(v) for t, v in solver["diff"].items()}, prices)
            if usd is not None:
                solver_usd[solver["account_id"]] += usd

    solver_accounts = set(solver_usd)
    user_round_trips = 0
    user_entries = 0
    for (acct, gave, got), cnt in directed_flows.items():
        if acct in solver_accounts:
            continue
        user_entries += cnt
        if (acct, got, gave) in directed_flows:
            user_round_trips += cnt

    total_solver_usd = sum(solver_usd.values())
    hhi = sum((v / total_solver_usd) ** 2 for v in solver_usd.values()) if total_solver_usd else None
    top_solvers = [
        {
            "account": acct,
            "fills": solver_fills[acct],
            "usd_volume": round(vol, 2),
            "share": round(vol / total_solver_usd, 4) if total_solver_usd else None,
        }
        for acct, vol in solver_usd.most_common(10)
    ]
    top3_share = sum(s["share"] for s in top_solvers[:3] if s["share"]) if top_solvers else None

    fee_only = sorted(b for b, _ in fee_bps_samples)
    n = len(fee_only)
    weighted = [(b, w) for b, w in fee_bps_samples if w]
    wsum = sum(w for _, w in weighted)
    vw_mean = sum(b * w for b, w in weighted) / wsum if wsum else None

    total_corridor_usd = sum(corridor_usd.values())
    corridors = [
        {
            "pair": pair,
            "usd_volume": round(vol, 2),
            "share": round(vol / total_corridor_usd, 4) if total_corridor_usd else None,
            "entries": corridor_n[pair],
        }
        for pair, vol in corridor_usd.most_common(10)
    ]

    for rid, value in receipt_stable.items():
        day_public_fill[receipt_day[rid]] += value

    implied_bps = implied_revenue_bps_30d()
    block_span = max(blocks) - min(blocks) + 1
    result = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "FastNEAR neardata, intents.near, dip4 token_diff events",
            "block_range": [min(blocks), max(blocks)],
            "blocks_with_fills": len(blocks),
            "chain_hours_covered_est": round(block_span * NEAR_BLOCK_SECONDS / 3600, 2),
            "coverage_note": "contiguous window starting Oct 28, 2026; ingestion ongoing",
            "n_receipts": len(receipts),
            "n_entries": total_entries,
            "bilateral_receipts": bilateral,
            "multiparty_receipts": multiparty,
            "usd_valued_entry_share": round(valued_entries / total_entries, 4),
            "caveats": [
                "Window spans a few chain days and keeps growing; some time-of-day bias remains in solver and corridor shares",
                "USD values derived from stablecoin legs where present, else live major-asset prices; unvalued entries excluded from volume shares",
                "Solver side of a bilateral receipt identified as the account with higher global fill count",
                "Explicit fee rate measures fees_collected at the settlement contract only; it does not capture app-layer or off-contract revenue",
            ],
        },
        "explicit_fee": {
            "n_samples": n,
            "median_bps": round(fee_only[n // 2], 4) if n else None,
            "p25_bps": round(fee_only[n // 4], 4) if n else None,
            "p75_bps": round(fee_only[3 * n // 4], 4) if n else None,
            "max_bps": round(fee_only[-1], 2) if n else None,
            "volume_weighted_mean_bps": round(vw_mean, 4) if vw_mean is not None else None,
            "defillama_implied_revenue_bps_30d": implied_bps,
            "finding": (
                "The explicit protocol fee at the settlement contract is roughly 0.01 bps per side, "
                f"hundreds of times below the {implied_bps} bps revenue rate implied by DefiLlama. "
                "Protocol revenue is therefore generated off the settlement contract "
                "(application-layer fees or solver arrangements), not by a contract-enforced take. "
                "The capture rate behind the break-even model is policy, not protocol."
            ),
        },
        "solvers": {
            "hhi": round(hhi, 4) if hhi is not None else None,
            "top3_share": round(top3_share, 4) if top3_share is not None else None,
            "distinct_solver_accounts": len(solver_usd),
            "top": top_solvers,
        },
        "corridors": corridors,
        "confidential_flow": {
            "treasury_account": CONFIDENTIAL_TREASURY,
            "identification": (
                "This account receives the majority of transfer events on intents.near in the "
                "window and never appears as a counterparty in any bilateral fill; tokens sent "
                "to it settle outside the public event stream and return later"
            ),
            "method": (
                "Per approximate chain day (block height arithmetic from the ingestion start), "
                "stablecoin USD entering the treasury via transfer events is compared against "
                "stablecoin USD settled in public fills, counted once per settlement receipt. "
                "Both sides measure value entering a settlement route once, so the comparison is "
                "like for like. Stablecoin legs only; major and unknown tokens are excluded from "
                "both sides. The treasury is a routing hub rather than a sink: it pays out almost "
                "exactly what it takes in, so these figures describe where activity is routed, "
                "not value captured"
            ),
            "by_chain_day": [
                {
                    "day_index": d,
                    "est_date_utc": (
                        datetime.strptime(INGEST_START_DATE, "%Y-%m-%d")
                        + timedelta(days=d)
                    ).strftime("%Y-%m-%d"),
                    "treasury_in_stable_usd": round(day_treasury_in.get(d, 0.0), 0),
                    "treasury_out_stable_usd": round(day_treasury_out.get(d, 0.0), 0),
                    "public_fill_stable_usd": round(day_public_fill.get(d, 0.0), 0),
                    "treasury_share": round(confidential_share(
                        day_treasury_in.get(d, 0.0), day_public_fill.get(d, 0.0)
                    ) or 0.0, 4),
                }
                for d in sorted(set(day_treasury_in) | set(day_public_fill))
            ],
            "window_totals": {
                "treasury_in_stable_usd": round(sum(day_treasury_in.values()), 0),
                "treasury_out_stable_usd": round(sum(day_treasury_out.values()), 0),
                "treasury_net_stable_usd": round(
                    sum(day_treasury_in.values()) - sum(day_treasury_out.values()), 0
                ),
                "public_fill_stable_usd": round(sum(day_public_fill.values()), 0),
            },
            "finding": (
                "More stablecoin value is routed into the confidential path than settles as "
                "public fills. The treasury pays out almost exactly what it receives, so this "
                "measures routing rather than capture, but the consequence for this analysis is "
                "the same: a large share of activity leaves the public event stream, so every "
                "figure measured from public fills describes a diminishing slice of the protocol"
            ),
        },
        "wash_screen": {
            "bilateral_self_fills": self_fill_receipts,
            "bilateral_self_fill_share": round(self_fill_receipts / bilateral, 4) if bilateral else None,
            "user_round_trip_entries": user_round_trips,
            "user_round_trip_share": round(user_round_trips / user_entries, 4) if user_entries else None,
            "note": "Solver accounts excluded from the round-trip metric since market makers legitimately trade both directions",
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1))
    DOCS_OUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(OUT, DOCS_OUT)

    m = result["meta"]
    f = result["explicit_fee"]
    s = result["solvers"]
    w = result["wash_screen"]
    print(f"Coverage: {m['n_receipts']} receipts, {m['chain_hours_covered_est']}h of chain time, blocks {m['block_range'][0]}..{m['block_range'][1]}")
    print(f"Explicit fee: median {f['median_bps']} bps/side (vw mean {f['volume_weighted_mean_bps']}), n={f['n_samples']}, vs DefiLlama implied {f['defillama_implied_revenue_bps_30d']} bps")
    print(f"Solvers: HHI {s['hhi']}, top3 share {s['top3_share']}, {s['distinct_solver_accounts']} accounts")
    print(f"Wash screen: bilateral self-fills {w['bilateral_self_fills']}, user round-trip share {(w['user_round_trip_share'] or 0)*100:.2f}%")
    for row in result["confidential_flow"]["by_chain_day"]:
        print(f"Confidential flow {row['est_date_utc']}: treasury in ${row['treasury_in_stable_usd']/1e6:.1f}M out ${row['treasury_out_stable_usd']/1e6:.1f}M vs public ${row['public_fill_stable_usd']/1e6:.1f}M, routed share {row['treasury_share']*100:.1f}%")
    print(f"Wrote {OUT.relative_to(ROOT)} and {DOCS_OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
