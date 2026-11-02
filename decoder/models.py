from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .token_id import TokenId


@dataclass
class TokenDiffItem:
    account_id: str
    intent_hash: Optional[str]
    diff: dict[str, int]
    fees_collected: dict[str, int]
    memo: Optional[str]
    referral: Optional[str]
    version: str
    block_height: Optional[int]
    block_timestamp_ns: Optional[int]
    tx_hash: Optional[str]
    receipt_id: Optional[str]
    executor_id: str


@dataclass
class IntentsExecutedItem:
    account_id: str
    intent_hash: Optional[str]
    nonce: str
    version: str
    block_height: Optional[int]
    block_timestamp_ns: Optional[int]
    tx_hash: Optional[str]
    receipt_id: Optional[str]
    executor_id: str


@dataclass
class TransferItem:
    account_id: str
    intent_hash: Optional[str]
    receiver_id: str
    tokens: dict[str, int]
    memo: Optional[str]
    version: str
    block_height: Optional[int]
    block_timestamp_ns: Optional[int]
    tx_hash: Optional[str]
    receipt_id: Optional[str]
    executor_id: str


@dataclass
class FtWithdrawItem:
    account_id: str
    intent_hash: Optional[str]
    token: str
    receiver_id: str
    amount: int
    memo: Optional[str]
    version: str
    block_height: Optional[int]
    block_timestamp_ns: Optional[int]
    tx_hash: Optional[str]
    receipt_id: Optional[str]
    executor_id: str


@dataclass
class MtWithdrawItem:
    account_id: str
    intent_hash: Optional[str]
    token: str
    receiver_id: str
    token_ids: list[str]
    amounts: list[int]
    memo: Optional[str]
    version: str
    block_height: Optional[int]
    block_timestamp_ns: Optional[int]
    tx_hash: Optional[str]
    receipt_id: Optional[str]
    executor_id: str


@dataclass
class NativeWithdrawItem:
    account_id: str
    intent_hash: Optional[str]
    receiver_id: str
    amount_yocto: int
    version: str
    block_height: Optional[int]
    block_timestamp_ns: Optional[int]
    tx_hash: Optional[str]
    receipt_id: Optional[str]
    executor_id: str


@dataclass
class FeeChangedItem:
    old_fee_pips: int
    new_fee_pips: int
    version: str
    block_height: Optional[int]
    block_timestamp_ns: Optional[int]
    tx_hash: Optional[str]
    receipt_id: Optional[str]
    executor_id: str


@dataclass
class FeeCollectorChangedItem:
    old_fee_collector: str
    new_fee_collector: str
    version: str
    block_height: Optional[int]
    block_timestamp_ns: Optional[int]
    tx_hash: Optional[str]
    receipt_id: Optional[str]
    executor_id: str


DecodedEvent = (
    TokenDiffItem
    | IntentsExecutedItem
    | TransferItem
    | FtWithdrawItem
    | MtWithdrawItem
    | NativeWithdrawItem
    | FeeChangedItem
    | FeeCollectorChangedItem
)
