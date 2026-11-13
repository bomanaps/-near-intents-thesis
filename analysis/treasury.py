"""
Confidential treasury float on intents.near, read from contract state.

The event-decoding path in analysis/onchain.py measures the confidential flow by
ingesting settlement events forward in time, so it can only describe the days it
has ingested. The same account's stablecoin holdings are contract state, and
state is addressable at any past block, so one view call per day reconstructs the
entire history of the float directly.

For each UTC day this module resolves a block within seconds of midnight on an
archival RPC, then calls mt_batch_balance_of on intents.near for the treasury
account over every stablecoin token id. Balances are exact integer token units
taken from state at that height; no price series is used and no event stream is
replayed. Stablecoin units are reported at face value, which is stated in the
output rather than assumed silently.

Day-over-day change in the float is a lower bound on that day's gross flow: a day
that routes value in and straight back out again shows no change at all.

Outputs data/raw/treasury_balances.json (the raw per-day reads, cached so reruns
only fetch missing days), data/model/treasury.json and docs/data/treasury.json.

Usage: python3 analysis/treasury.py [--refresh]
"""

from __future__ import annotations

import json
import shutil
import sys
import time
import urllib.error
import urllib.request
from base64 import b64encode
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

ROOT = Path(__file__).parent.parent
CACHE = ROOT / "data" / "raw" / "treasury_balances.json"
OUT = ROOT / "data" / "model" / "treasury.json"
DOCS_OUT = ROOT / "docs" / "data" / "treasury.json"
ONCHAIN = ROOT / "data" / "model" / "onchain.json"

RPC_ENDPOINTS = [
    "https://archival-rpc.mainnet.fastnear.com",
    "https://archival-rpc.mainnet.near.org",
]

CONTRACT = "intents.near"
METHOD = "mt_batch_balance_of"
TREASURY = "51e8f94d77b5e90dc9852ca6113771e11e8382ce69473a75e313e41665de7cbe"

STABLES = {
    "nep141:eth-0xdac17f958d2ee523a2206206994597c13d831ec7.omft.near": ("USDT.eth", 6),
    "nep141:eth-0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48.omft.near": ("USDC.eth", 6),
    "nep141:tron-d28a265909efecdcee7c5028585214ea0b96f015.omft.near": ("USDT.tron", 6),
    "nep141:base-0x833589fcd6edb6e08f4c7c32d4f71b54bda02913.omft.near": ("USDC.base", 6),
    "nep141:arb-0xaf88d065e77c8cc2239327c5edb3a432268e5831.omft.near": ("USDC.arb", 6),
    "nep141:arb-0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9.omft.near": ("USDT.arb", 6),
    "nep141:eth-0x6b175474e89094c44da98b954eedeac495271d0f.omft.near": ("DAI.eth", 18),
}

TOKEN_IDS = sorted(STABLES)
SEARCH_START_HEIGHT = 180_000_000
BLOCK_SECONDS = 0.6
GAP_SCAN_BLOCKS = 600
TARGET_TOLERANCE_SECONDS = 30
MAX_INTERPOLATIONS = 10
MIN_CALL_INTERVAL = 0.22
THROTTLE_BACKOFF_SECONDS = 2.0


class RpcError(RuntimeError):
    pass


_last_call = [0.0]
_calls = [0]


def rpc(method: str, params: dict, attempts: int = 9) -> dict:
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": "basanos", "method": method, "params": params}
    ).encode()
    last = None
    for attempt in range(attempts):
        wait = MIN_CALL_INTERVAL - (time.monotonic() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _calls[0] += 1
        url = RPC_ENDPOINTS[attempt % len(RPC_ENDPOINTS)]
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                body = json.load(r)
            _last_call[0] = time.monotonic()
        except urllib.error.HTTPError as exc:
            _last_call[0] = time.monotonic()
            last = exc
            if exc.code == 429:
                time.sleep(THROTTLE_BACKOFF_SECONDS * 2**attempt)
                continue
            try:
                body = json.loads(exc.read().decode())
            except (ValueError, OSError):
                time.sleep(0.5 * (attempt + 1))
                continue
            if "error" in body:
                return body
            time.sleep(0.5 * (attempt + 1))
            continue
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            _last_call[0] = time.monotonic()
            last = exc
            time.sleep(0.5 * (attempt + 1))
            continue
        return body
    raise RpcError(f"{method} failed after {attempts} attempts: {last}")


def block_at_or_after(height: int) -> dict:
    for offset in range(GAP_SCAN_BLOCKS):
        body = rpc("block", {"block_id": height + offset})
        if "error" not in body:
            return body["result"]["header"]
    raise RpcError(f"no block found within {GAP_SCAN_BLOCKS} of height {height}")


def head_header() -> dict:
    body = rpc("block", {"finality": "final"})
    if "error" in body:
        raise RpcError(f"head query failed: {body['error']}")
    return body["result"]["header"]


def seconds_of(header: dict) -> float:
    return int(header["timestamp"]) / 1e9


_rate = [BLOCK_SECONDS]


def observe_rate(first: dict, second: dict) -> None:
    span = int(second["height"]) - int(first["height"])
    if span < 10_000:
        return
    rate = (seconds_of(second) - seconds_of(first)) / span
    if 0.2 <= rate <= 5.0:
        _rate[0] = rate


def resolve_height(target_epoch: float, anchor: dict) -> dict:
    height = int(anchor["height"]) + int(
        (target_epoch - seconds_of(anchor)) / _rate[0]
    )
    height = max(height, SEARCH_START_HEIGHT)
    header = block_at_or_after(height)
    observe_rate(anchor, header)
    for _ in range(MAX_INTERPOLATIONS):
        drift = target_epoch - seconds_of(header)
        if abs(drift) <= TARGET_TOLERANCE_SECONDS:
            break
        height = max(int(header["height"]) + int(drift / _rate[0]), SEARCH_START_HEIGHT)
        header = block_at_or_after(height)
    while seconds_of(header) < target_epoch:
        jump = max(1, int((target_epoch - seconds_of(header)) / _rate[0]))
        header = block_at_or_after(int(header["height"]) + jump)
    observe_rate(anchor, header)
    return header


def balances_at(height: int) -> dict[str, int]:
    args = b64encode(
        json.dumps({"account_id": TREASURY, "token_ids": TOKEN_IDS}).encode()
    ).decode()
    body = rpc(
        "query",
        {
            "request_type": "call_function",
            "account_id": CONTRACT,
            "method_name": METHOD,
            "args_base64": args,
            "block_id": height,
        },
    )
    if "error" in body:
        raise RpcError(f"view call failed at height {height}: {body['error']}")
    raw = json.loads(bytes(body["result"]["result"]).decode())
    return {tok: int(value) for tok, value in zip(TOKEN_IDS, raw)}


def face_value_usd(balances: dict[str, int]) -> float:
    total = 0.0
    for tok, units in balances.items():
        _, decimals = STABLES[tok]
        total += units / 10**decimals
    return total


def load_cache() -> dict:
    if CACHE.exists():
        return json.loads(CACHE.read_text())
    return {}


def save_cache(cache: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n")


def day_range(first: str, last: str) -> list[str]:
    start = datetime.strptime(first, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(last, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    days = []
    while start <= end:
        days.append(start.strftime("%Y-%m-%d"))
        start += timedelta(days=1)
    return days


def first_funded_height(head: dict) -> int:
    low, high = SEARCH_START_HEIGHT, int(head["height"])
    if any(balances_at(block_at_or_after(low)["height"]).values()):
        return int(block_at_or_after(low)["height"])
    while low < high - 1:
        mid = (low + high) // 2
        header = block_at_or_after(mid)
        height = int(header["height"])
        if any(balances_at(height).values()):
            high = height
        else:
            low = height
    return high


def collect(refresh: bool) -> dict:
    head = head_header()
    cache = {} if refresh else load_cache()

    funded_key = "_first_funded"
    if funded_key in cache:
        funded_height = int(cache[funded_key]["block_height"])
        funded_date = cache[funded_key]["date_utc"]
    else:
        funded_height = first_funded_height(head)
        header = block_at_or_after(funded_height)
        funded_date = datetime.fromtimestamp(seconds_of(header), timezone.utc).strftime(
            "%Y-%m-%d"
        )
        cache[funded_key] = {
            "block_height": funded_height,
            "date_utc": funded_date,
            "block_time_utc": datetime.fromtimestamp(
                seconds_of(header), timezone.utc
            ).isoformat(),
        }
        save_cache(cache)

    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    days = day_range(funded_date, yesterday)

    anchor = head
    missing = [d for d in days if d not in cache]
    print(f"      {len(days)} UTC days from {funded_date}, {len(missing)} to fetch")
    for n, day in enumerate(days):
        if day in cache:
            anchor = {
                "height": cache[day]["block_height"],
                "timestamp": int(cache[day]["block_epoch"] * 1e9),
            }
            continue
        target = (
            datetime.strptime(day, "%Y-%m-%d")
            .replace(tzinfo=timezone.utc)
            .timestamp()
        )
        header = resolve_height(target, anchor)
        height = int(header["height"])
        balances = balances_at(height)
        cache[day] = {
            "block_height": height,
            "block_epoch": seconds_of(header),
            "block_time_utc": datetime.fromtimestamp(
                seconds_of(header), timezone.utc
            ).isoformat(),
            "balances": {STABLES[t][0]: str(v) for t, v in balances.items()},
            "stable_float_usd": round(face_value_usd(balances), 2),
        }
        anchor = {"height": height, "timestamp": int(seconds_of(header) * 1e9)}
        if n % 10 == 0:
            save_cache(cache)
            print(f"      {day} height {height} float ${cache[day]['stable_float_usd']:,.0f} "
                  f"({_calls[0]} rpc calls, {_rate[0]:.3f}s per block)")
    save_cache(cache)
    return cache


def ingested_chain_days() -> int | None:
    if not ONCHAIN.exists():
        return None
    flow = json.loads(ONCHAIN.read_text()).get("confidential_flow", {})
    rows = flow.get("by_chain_day") or []
    return len(rows) or None


def measured_daily_flow() -> float | None:
    if not ONCHAIN.exists():
        return None
    flow = json.loads(ONCHAIN.read_text()).get("confidential_flow", {})
    rows = flow.get("by_chain_day") or []
    if not rows:
        return None
    totals = [
        float(r["treasury_in_stable_usd"]) + float(r["treasury_out_stable_usd"])
        for r in rows
    ]
    return sum(totals) / len(totals)


def build(cache: dict) -> dict:
    funded = cache["_first_funded"]
    days = sorted(d for d in cache if not d.startswith("_"))
    series = []
    previous = None
    for day in days:
        row = cache[day]
        value = float(row["stable_float_usd"])
        series.append(
            {
                "date_utc": day,
                "block_height": int(row["block_height"]),
                "block_time_utc": row["block_time_utc"],
                "balances_token_units": row["balances"],
                "stable_float_usd": round(value, 2),
                "change_usd": None if previous is None else round(value - previous, 2),
            }
        )
        previous = value

    floats = [r["stable_float_usd"] for r in series]
    changes = [r["change_usd"] for r in series if r["change_usd"] is not None]
    peak = max(series, key=lambda r: r["stable_float_usd"])
    flow = measured_daily_flow()
    latest = series[-1]["stable_float_usd"]

    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "source": {
            "method": f"{CONTRACT} {METHOD} at historical block heights",
            "rpc_endpoints": RPC_ENDPOINTS,
            "account_id": TREASURY,
            "token_ids": TOKEN_IDS,
            "note": (
                "Balances are exact integer token units read from contract state at "
                "the resolved block for each UTC midnight, whose exact height and "
                "timestamp are recorded on every row. No event stream is replayed "
                "and no price series is used."
            ),
            "assumption": (
                "Stablecoin units are summed at face value, one unit of USDT, USDC "
                "or DAI counted as one dollar. Depeg risk is not modelled."
            ),
        },
        "coverage": {
            "first_funded_block": int(funded["block_height"]),
            "first_funded_date_utc": funded["date_utc"],
            "last_date_utc": series[-1]["date_utc"],
            "days": len(series),
            "days_ingested_by_events": ingested_chain_days(),
            "note": (
                "The first funded block is located by bisection, which assumes the "
                "account does not return to a zero balance once funded. The daily "
                "series is read independently of that search, so any zero day it "
                "contains is a measurement, not an artefact of the search."
            ),
        },
        "summary": {
            "latest_float_usd": round(latest, 2),
            "peak_float_usd": round(peak["stable_float_usd"], 2),
            "peak_date_utc": peak["date_utc"],
            "mean_float_usd": round(sum(floats) / len(floats), 2),
            "median_float_usd": round(median(floats), 2),
            "mean_abs_daily_change_usd": (
                round(sum(abs(c) for c in changes) / len(changes), 2) if changes else None
            ),
            "largest_daily_increase_usd": round(max(changes), 2) if changes else None,
            "largest_daily_decrease_usd": round(min(changes), 2) if changes else None,
            "measured_mean_daily_gross_flow_usd": (
                round(flow, 2) if flow is not None else None
            ),
            "float_in_days_of_measured_flow": (
                round(latest / flow, 2) if flow else None
            ),
        },
        "interpretation": (
            "The float is working capital, not a sink. It is held in stablecoins, "
            "it turns over in days rather than accumulating indefinitely, and its "
            "day-over-day change is a lower bound on that day's gross routing, "
            "because value routed in and out within one day leaves no trace in the "
            "balance."
        ),
        "series": series,
    }


def main() -> None:
    refresh = "--refresh" in sys.argv[1:]
    cache = collect(refresh)
    result = build(cache)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2) + "\n")
    DOCS_OUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(OUT, DOCS_OUT)

    c, s = result["coverage"], result["summary"]
    print(f"Treasury float history: {c['days']} UTC days from {c['first_funded_date_utc']} to {c['last_date_utc']}")
    print(f"Latest float ${s['latest_float_usd']/1e6:.1f}M, peak ${s['peak_float_usd']/1e6:.1f}M on {s['peak_date_utc']}, median ${s['median_float_usd']/1e6:.1f}M")
    if s["float_in_days_of_measured_flow"]:
        print(f"Float is {s['float_in_days_of_measured_flow']:.2f} days of measured gross routing")
    print(f"Wrote {OUT.relative_to(ROOT)} and {DOCS_OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
