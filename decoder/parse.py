from __future__ import annotations

import json
from typing import Any, Iterator, Optional

from .models import (
    DecodedEvent,
    FeeChangedItem,
    FeeCollectorChangedItem,
    FtWithdrawItem,
    IntentsExecutedItem,
    MtWithdrawItem,
    NativeWithdrawItem,
    TokenDiffItem,
    TransferItem,
)

_EVENT_JSON_PREFIX = "EVENT_JSON:"
_INTENTS_EXECUTORS = frozenset({"intents.near", "defuse-alpha.near"})


class DecodeError(Exception):
    pass


def decode_log_line(
    log: str,
    executor_id: str,
    block_height: Optional[int] = None,
    block_timestamp_ns: Optional[int] = None,
    tx_hash: Optional[str] = None,
    receipt_id: Optional[str] = None,
) -> Optional[list[DecodedEvent]]:
    if executor_id not in _INTENTS_EXECUTORS:
        return None
    if not log.startswith(_EVENT_JSON_PREFIX):
        return None

    raw = log[len(_EVENT_JSON_PREFIX) :]
    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DecodeError(f"Invalid JSON in log: {exc}") from exc

    if envelope.get("standard") != "dip4":
        return None

    version: str = envelope.get("version", "")
    event_name: str = envelope.get("event", "")
    data: Any = envelope.get("data")

    ctx = dict(
        version=version,
        block_height=block_height,
        block_timestamp_ns=block_timestamp_ns,
        tx_hash=tx_hash,
        receipt_id=receipt_id,
        executor_id=executor_id,
    )

    if event_name == "token_diff":
        return list(_parse_token_diff(data, version, ctx))
    if event_name == "intents_executed":
        return list(_parse_intents_executed(data, version, ctx))
    if event_name == "transfer":
        return list(_parse_transfer(data, version, ctx))
    if event_name == "ft_withdraw":
        return list(_parse_ft_withdraw(data, version, ctx))
    if event_name == "mt_withdraw":
        return list(_parse_mt_withdraw(data, version, ctx))
    if event_name == "native_withdraw":
        return list(_parse_native_withdraw(data, version, ctx))
    if event_name == "fee_changed":
        return [_parse_fee_changed(data, ctx)]
    if event_name == "fee_collector_changed":
        return [_parse_fee_collector_changed(data, ctx)]

    return None


def decode_receipt_logs(
    logs: list[str],
    executor_id: str,
    block_height: Optional[int] = None,
    block_timestamp_ns: Optional[int] = None,
    tx_hash: Optional[str] = None,
    receipt_id: Optional[str] = None,
) -> list[DecodedEvent]:
    out: list[DecodedEvent] = []
    for log in logs:
        result = decode_log_line(
            log,
            executor_id=executor_id,
            block_height=block_height,
            block_timestamp_ns=block_timestamp_ns,
            tx_hash=tx_hash,
            receipt_id=receipt_id,
        )
        if result is None:
            continue
        if isinstance(result, list):
            out.extend(result)
        else:
            out.append(result)
    return out


def _maybe_intent_hash(item: dict, version: str) -> Optional[str]:
    raw = item.get("intent_hash")
    if raw is None and _version_lt(version, "0.4.3"):
        raise DecodeError(
            f"intent_hash required for version {version!r} but missing in {item!r}"
        )
    return raw


def _version_lt(v: str, threshold: str) -> bool:
    def parts(s: str) -> tuple[int, ...]:
        try:
            return tuple(int(x) for x in s.split("."))
        except ValueError:
            return (0, 0, 0)

    return parts(v) < parts(threshold)


def _parse_token_diff(
    data: Any, version: str, ctx: dict
) -> Iterator[TokenDiffItem]:
    if not isinstance(data, list):
        raise DecodeError(f"token_diff data must be a list, got {type(data)}")

    for item in data:
        if not isinstance(item, dict):
            raise DecodeError(f"token_diff item must be a dict, got {type(item)}")

        intent_hash = _maybe_intent_hash(item, version)

        raw_diff = item.get("diff")
        if not isinstance(raw_diff, dict):
            raise DecodeError(f"token_diff.diff must be a dict, got {type(raw_diff)}")

        diff = {k: int(v) for k, v in raw_diff.items()}

        raw_fees = item.get("fees_collected") or {}
        if not isinstance(raw_fees, dict):
            raise DecodeError(
                f"token_diff.fees_collected must be a dict, got {type(raw_fees)}"
            )
        fees_collected = {k: int(v) for k, v in raw_fees.items()}

        yield TokenDiffItem(
            account_id=_require_str(item, "account_id"),
            intent_hash=intent_hash,
            diff=diff,
            fees_collected=fees_collected,
            memo=item.get("memo"),
            referral=item.get("referral"),
            **ctx,
        )


def _parse_intents_executed(
    data: Any, version: str, ctx: dict
) -> Iterator[IntentsExecutedItem]:
    if not isinstance(data, list):
        raise DecodeError(
            f"intents_executed data must be a list, got {type(data)}"
        )

    for item in data:
        if not isinstance(item, dict):
            raise DecodeError(
                f"intents_executed item must be a dict, got {type(item)}"
            )

        intent_hash = _maybe_intent_hash(item, version)

        yield IntentsExecutedItem(
            account_id=_require_str(item, "account_id"),
            intent_hash=intent_hash,
            nonce=_require_str(item, "nonce"),
            **ctx,
        )


def _parse_transfer(
    data: Any, version: str, ctx: dict
) -> Iterator[TransferItem]:
    if not isinstance(data, list):
        raise DecodeError(f"transfer data must be a list, got {type(data)}")

    for item in data:
        if not isinstance(item, dict):
            raise DecodeError(f"transfer item must be a dict, got {type(item)}")

        intent_hash = _maybe_intent_hash(item, version)

        raw_tokens = item.get("tokens")
        if not isinstance(raw_tokens, dict):
            raise DecodeError(
                f"transfer.tokens must be a dict, got {type(raw_tokens)}"
            )
        tokens = {k: int(v) for k, v in raw_tokens.items()}

        yield TransferItem(
            account_id=_require_str(item, "account_id"),
            intent_hash=intent_hash,
            receiver_id=_require_str(item, "receiver_id"),
            tokens=tokens,
            memo=item.get("memo"),
            **ctx,
        )


def _parse_ft_withdraw(
    data: Any, version: str, ctx: dict
) -> Iterator[FtWithdrawItem]:
    if not isinstance(data, list):
        raise DecodeError(f"ft_withdraw data must be a list, got {type(data)}")

    for item in data:
        if not isinstance(item, dict):
            raise DecodeError(f"ft_withdraw item must be a dict, got {type(item)}")

        intent_hash = _maybe_intent_hash(item, version)

        yield FtWithdrawItem(
            account_id=_require_str(item, "account_id"),
            intent_hash=intent_hash,
            token=_require_str(item, "token"),
            receiver_id=_require_str(item, "receiver_id"),
            amount=int(_require_str(item, "amount")),
            memo=item.get("memo"),
            **ctx,
        )


def _parse_mt_withdraw(
    data: Any, version: str, ctx: dict
) -> Iterator[MtWithdrawItem]:
    if not isinstance(data, list):
        raise DecodeError(f"mt_withdraw data must be a list, got {type(data)}")

    for item in data:
        if not isinstance(item, dict):
            raise DecodeError(f"mt_withdraw item must be a dict, got {type(item)}")

        intent_hash = _maybe_intent_hash(item, version)

        raw_amounts = item.get("amounts", [])
        amounts = [int(a) for a in raw_amounts]

        token_ids = item.get("token_ids", [])
        if not isinstance(token_ids, list):
            raise DecodeError(
                f"mt_withdraw.token_ids must be a list, got {type(token_ids)}"
            )

        yield MtWithdrawItem(
            account_id=_require_str(item, "account_id"),
            intent_hash=intent_hash,
            token=_require_str(item, "token"),
            receiver_id=_require_str(item, "receiver_id"),
            token_ids=token_ids,
            amounts=amounts,
            memo=item.get("memo"),
            **ctx,
        )


def _parse_native_withdraw(
    data: Any, version: str, ctx: dict
) -> Iterator[NativeWithdrawItem]:
    if not isinstance(data, list):
        raise DecodeError(
            f"native_withdraw data must be a list, got {type(data)}"
        )

    for item in data:
        if not isinstance(item, dict):
            raise DecodeError(
                f"native_withdraw item must be a dict, got {type(item)}"
            )

        intent_hash = _maybe_intent_hash(item, version)

        raw_amount = item.get("amount")
        if isinstance(raw_amount, dict):
            amount_yocto = int(raw_amount.get("amount", 0))
        elif isinstance(raw_amount, (int, str)):
            amount_yocto = int(raw_amount)
        else:
            raise DecodeError(
                f"native_withdraw.amount has unexpected type {type(raw_amount)}"
            )

        yield NativeWithdrawItem(
            account_id=_require_str(item, "account_id"),
            intent_hash=intent_hash,
            receiver_id=_require_str(item, "receiver_id"),
            amount_yocto=amount_yocto,
            **ctx,
        )


def _parse_fee_changed(data: Any, ctx: dict) -> FeeChangedItem:
    if not isinstance(data, dict):
        raise DecodeError(f"fee_changed data must be a dict, got {type(data)}")

    return FeeChangedItem(
        old_fee_pips=int(data["old_fee"]),
        new_fee_pips=int(data["new_fee"]),
        **ctx,
    )


def _parse_fee_collector_changed(data: Any, ctx: dict) -> FeeCollectorChangedItem:
    if not isinstance(data, dict):
        raise DecodeError(
            f"fee_collector_changed data must be a dict, got {type(data)}"
        )

    return FeeCollectorChangedItem(
        old_fee_collector=str(data["old_fee_collector"]),
        new_fee_collector=str(data["new_fee_collector"]),
        **ctx,
    )


def _require_str(d: dict, key: str) -> str:
    val = d.get(key)
    if val is None:
        raise DecodeError(f"Required field {key!r} missing from {d!r}")
    return str(val)
