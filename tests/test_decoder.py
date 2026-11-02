import json
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from decoder import (
    DecodeError,
    FeeChangedItem,
    FeeCollectorChangedItem,
    FtWithdrawItem,
    IntentsExecutedItem,
    MtWithdrawItem,
    NativeWithdrawItem,
    TokenDiffItem,
    TransferItem,
    decode_log_line,
    decode_receipt_logs,
)
from decoder.token_id import (
    ImtTokenId,
    Nep141TokenId,
    Nep171TokenId,
    Nep245TokenId,
    TokenKind,
    parse_token_id,
)


class TestParseTokenId:
    def test_nep141(self):
        t = parse_token_id("nep141:wrap.near")
        assert isinstance(t, Nep141TokenId)
        assert t.contract_id == "wrap.near"
        assert t.kind == TokenKind.NEP141
        assert str(t) == "nep141:wrap.near"

    def test_nep245_hot_bridge(self):
        t = parse_token_id("nep245:v2.omni.hot.tg:nep141:eth_0xdac17f958d2ee523a2206206994597c13d831ec7")
        assert isinstance(t, Nep245TokenId)
        assert t.contract_id == "v2.omni.hot.tg"
        assert t.mt_token_id == "nep141:eth_0xdac17f958d2ee523a2206206994597c13d831ec7"
        assert t.kind == TokenKind.NEP245
        assert str(t) == "nep245:v2.omni.hot.tg:nep141:eth_0xdac17f958d2ee523a2206206994597c13d831ec7"

    def test_nep171(self):
        t = parse_token_id("nep171:nft.near:token123")
        assert isinstance(t, Nep171TokenId)
        assert t.contract_id == "nft.near"
        assert t.token_id == "token123"
        assert t.kind == TokenKind.NEP171
        assert str(t) == "nep171:nft.near:token123"

    def test_imt(self):
        t = parse_token_id("imt:imt.near:sometoken")
        assert isinstance(t, ImtTokenId)
        assert t.contract_id == "imt.near"
        assert t.token_id == "sometoken"
        assert t.kind == TokenKind.IMT
        assert str(t) == "imt:imt.near:sometoken"

    def test_missing_prefix_separator_raises(self):
        with pytest.raises(ValueError, match="missing prefix separator"):
            parse_token_id("wrap.near")

    def test_unknown_prefix_raises(self):
        with pytest.raises(ValueError, match="Unknown TokenId prefix"):
            parse_token_id("nep999:wrap.near")

    def test_nep245_missing_second_separator_raises(self):
        with pytest.raises(ValueError, match="missing second separator"):
            parse_token_id("nep245:nodot")

    def test_nep171_missing_second_separator_raises(self):
        with pytest.raises(ValueError, match="missing second separator"):
            parse_token_id("nep171:nft.near")

    def test_imt_missing_second_separator_raises(self):
        with pytest.raises(ValueError, match="missing second separator"):
            parse_token_id("imt:imt.near")


class TestExecutorFilter:
    def test_ignores_non_intents_executor(self):
        log = 'EVENT_JSON:{"standard":"dip4","version":"0.4.3","event":"token_diff","data":[]}'
        assert decode_log_line(log, executor_id="other.near") is None

    def test_accepts_intents_near(self):
        log = 'EVENT_JSON:{"standard":"dip4","version":"0.4.3","event":"token_diff","data":[]}'
        result = decode_log_line(log, executor_id="intents.near")
        assert result == []

    def test_accepts_defuse_alpha_near(self):
        log = 'EVENT_JSON:{"standard":"dip4","version":"0.4.3","event":"token_diff","data":[]}'
        result = decode_log_line(log, executor_id="defuse-alpha.near")
        assert result == []

    def test_ignores_non_event_json_prefix(self):
        log = "some other log line"
        assert decode_log_line(log, executor_id="intents.near") is None

    def test_ignores_non_dip4_standard(self):
        log = 'EVENT_JSON:{"standard":"nep171","version":"1.0.0","event":"nft_mint","data":[]}'
        assert decode_log_line(log, executor_id="intents.near") is None

    def test_unknown_event_name_returns_none(self):
        log = "EVENT_JSON:" + json.dumps({
            "standard": "dip4",
            "version": "0.4.3",
            "event": "public_key_added",
            "data": [{"account_id": "user.near"}],
        })
        assert decode_log_line(log, executor_id="intents.near") is None

    def test_nft_withdraw_event_returns_none(self):
        log = "EVENT_JSON:" + json.dumps({
            "standard": "dip4",
            "version": "0.4.3",
            "event": "nft_withdraw",
            "data": [{"account_id": "user.near", "token": "nft.near", "receiver_id": "user.near", "token_id": "1"}],
        })
        assert decode_log_line(log, executor_id="intents.near") is None

    def test_storage_deposit_event_returns_none(self):
        log = "EVENT_JSON:" + json.dumps({
            "standard": "dip4",
            "version": "0.4.3",
            "event": "storage_deposit",
            "data": [{"account_id": "user.near", "contract_id": "token.near", "deposit_for_account_id": "user.near", "amount": {"amount": 1250000000000000000000}}],
        })
        assert decode_log_line(log, executor_id="intents.near") is None


class TestTokenDiffV043:
    def _make_log(self, items: list) -> str:
        return "EVENT_JSON:" + json.dumps(
            {"standard": "dip4", "version": "0.4.3", "event": "token_diff", "data": items}
        )

    def test_basic_swap(self):
        log = self._make_log([
            {
                "intent_hash": "3HvWYFZ3rRG8CcQsj7UAAVZ5wT1WMzCbHN5mgnGXwyz8",
                "account_id": "user.near",
                "diff": {
                    "nep141:usdc.near": "-1000000",
                    "nep141:wrap.near": "2500000000000000000000000",
                },
                "fees_collected": {"nep141:usdc.near": "100"},
                "referral": "1click.near",
            }
        ])
        result = decode_log_line(log, executor_id="intents.near", block_height=120000000)
        assert isinstance(result, list)
        assert len(result) == 1
        item = result[0]
        assert isinstance(item, TokenDiffItem)
        assert item.account_id == "user.near"
        assert item.intent_hash == "3HvWYFZ3rRG8CcQsj7UAAVZ5wT1WMzCbHN5mgnGXwyz8"
        assert item.diff["nep141:usdc.near"] == -1000000
        assert item.diff["nep141:wrap.near"] == 2500000000000000000000000
        assert item.fees_collected["nep141:usdc.near"] == 100
        assert item.referral == "1click.near"
        assert item.memo is None
        assert item.version == "0.4.3"
        assert item.block_height == 120000000
        assert item.executor_id == "intents.near"

    def test_nep245_token_in_diff(self):
        log = self._make_log([
            {
                "account_id": "solver.near",
                "diff": {
                    "nep245:v2.omni.hot.tg:nep141:eth_0xdac17f958d2ee523a2206206994597c13d831ec7": "-5000000",
                    "nep141:usdc.near": "4995000",
                },
                "fees_collected": {"nep245:v2.omni.hot.tg:nep141:eth_0xdac17f958d2ee523a2206206994597c13d831ec7": "5000"},
            }
        ])
        result = decode_log_line(log, executor_id="intents.near")
        item = result[0]
        assert item.diff["nep245:v2.omni.hot.tg:nep141:eth_0xdac17f958d2ee523a2206206994597c13d831ec7"] == -5000000
        assert item.fees_collected["nep245:v2.omni.hot.tg:nep141:eth_0xdac17f958d2ee523a2206206994597c13d831ec7"] == 5000

    def test_intent_hash_optional_in_v043(self):
        log = self._make_log([
            {
                "account_id": "solver.near",
                "diff": {"nep141:usdc.near": "1000000"},
                "fees_collected": {},
            }
        ])
        result = decode_log_line(log, executor_id="intents.near")
        assert result[0].intent_hash is None

    def test_empty_fees_collected_absent(self):
        log = self._make_log([
            {
                "account_id": "user.near",
                "diff": {"nep141:usdc.near": "-500"},
            }
        ])
        result = decode_log_line(log, executor_id="intents.near")
        assert result[0].fees_collected == {}

    def test_multiple_items(self):
        log = self._make_log([
            {"account_id": "a.near", "diff": {"nep141:usdc.near": "-100"}, "fees_collected": {"nep141:usdc.near": "1"}},
            {"account_id": "b.near", "diff": {"nep141:usdc.near": "99"}, "fees_collected": {}},
        ])
        result = decode_log_line(log, executor_id="intents.near")
        assert len(result) == 2
        assert result[0].account_id == "a.near"
        assert result[1].account_id == "b.near"


class TestTokenDiffV041:
    def test_missing_intent_hash_raises(self):
        log = "EVENT_JSON:" + json.dumps({
            "standard": "dip4",
            "version": "0.4.1",
            "event": "token_diff",
            "data": [
                {"account_id": "user.near", "diff": {"nep141:usdc.near": "-100"}, "fees_collected": {}}
            ],
        })
        with pytest.raises(DecodeError, match="intent_hash required"):
            decode_log_line(log, executor_id="intents.near")

    def test_present_intent_hash_passes(self):
        log = "EVENT_JSON:" + json.dumps({
            "standard": "dip4",
            "version": "0.4.1",
            "event": "token_diff",
            "data": [
                {
                    "intent_hash": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
                    "account_id": "user.near",
                    "diff": {"nep141:usdc.near": "-100"},
                    "fees_collected": {},
                }
            ],
        })
        result = decode_log_line(log, executor_id="intents.near")
        assert len(result) == 1
        assert result[0].intent_hash == "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
        assert result[0].version == "0.4.1"


class TestIntentsExecuted:
    def test_basic(self):
        log = "EVENT_JSON:" + json.dumps({
            "standard": "dip4",
            "version": "0.4.3",
            "event": "intents_executed",
            "data": [
                {
                    "intent_hash": "AbCdEfGhIjKlMnOpQrStUvWxYz1234567890ABCDE=",
                    "account_id": "user.near",
                    "nonce": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
                }
            ],
        })
        result = decode_log_line(log, executor_id="intents.near")
        assert len(result) == 1
        item = result[0]
        assert isinstance(item, IntentsExecutedItem)
        assert item.account_id == "user.near"
        assert item.intent_hash == "AbCdEfGhIjKlMnOpQrStUvWxYz1234567890ABCDE="
        assert item.nonce == "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
        assert item.version == "0.4.3"
        assert item.executor_id == "intents.near"

    def test_multiple_items(self):
        log = "EVENT_JSON:" + json.dumps({
            "standard": "dip4",
            "version": "0.4.3",
            "event": "intents_executed",
            "data": [
                {"intent_hash": "hash1", "account_id": "a.near", "nonce": "nonce1"},
                {"intent_hash": "hash2", "account_id": "b.near", "nonce": "nonce2"},
            ],
        })
        result = decode_log_line(log, executor_id="intents.near")
        assert len(result) == 2
        assert result[0].account_id == "a.near"
        assert result[1].account_id == "b.near"


class TestTransfer:
    def test_basic(self):
        log = "EVENT_JSON:" + json.dumps({
            "standard": "dip4",
            "version": "0.4.3",
            "event": "transfer",
            "data": [
                {
                    "intent_hash": "someHash",
                    "account_id": "sender.near",
                    "receiver_id": "receiver.near",
                    "tokens": {"nep141:usdc.near": "5000000"},
                    "memo": "payment",
                }
            ],
        })
        result = decode_log_line(log, executor_id="intents.near")
        assert len(result) == 1
        item = result[0]
        assert isinstance(item, TransferItem)
        assert item.account_id == "sender.near"
        assert item.intent_hash == "someHash"
        assert item.receiver_id == "receiver.near"
        assert item.tokens["nep141:usdc.near"] == 5000000
        assert item.memo == "payment"
        assert item.version == "0.4.3"
        assert item.executor_id == "intents.near"

    def test_memo_absent(self):
        log = "EVENT_JSON:" + json.dumps({
            "standard": "dip4",
            "version": "0.4.3",
            "event": "transfer",
            "data": [
                {
                    "account_id": "sender.near",
                    "receiver_id": "receiver.near",
                    "tokens": {"nep141:usdc.near": "1"},
                }
            ],
        })
        result = decode_log_line(log, executor_id="intents.near")
        assert result[0].memo is None


class TestFtWithdraw:
    def test_basic(self):
        log = "EVENT_JSON:" + json.dumps({
            "standard": "dip4",
            "version": "0.4.3",
            "event": "ft_withdraw",
            "data": [
                {
                    "intent_hash": "someHash",
                    "account_id": "user.near",
                    "token": "usdc.near",
                    "receiver_id": "wallet.near",
                    "amount": "1000000",
                    "memo": "out",
                }
            ],
        })
        result = decode_log_line(log, executor_id="intents.near")
        assert len(result) == 1
        item = result[0]
        assert isinstance(item, FtWithdrawItem)
        assert item.account_id == "user.near"
        assert item.intent_hash == "someHash"
        assert item.token == "usdc.near"
        assert item.receiver_id == "wallet.near"
        assert item.amount == 1000000
        assert item.memo == "out"
        assert item.version == "0.4.3"
        assert item.executor_id == "intents.near"

    def test_memo_absent(self):
        log = "EVENT_JSON:" + json.dumps({
            "standard": "dip4",
            "version": "0.4.3",
            "event": "ft_withdraw",
            "data": [
                {
                    "account_id": "user.near",
                    "token": "usdc.near",
                    "receiver_id": "wallet.near",
                    "amount": "1",
                }
            ],
        })
        result = decode_log_line(log, executor_id="intents.near")
        assert result[0].memo is None


class TestMtWithdraw:
    def test_basic(self):
        log = "EVENT_JSON:" + json.dumps({
            "standard": "dip4",
            "version": "0.4.3",
            "event": "mt_withdraw",
            "data": [
                {
                    "intent_hash": "someHash",
                    "account_id": "user.near",
                    "token": "v2.omni.hot.tg",
                    "receiver_id": "0xabc123",
                    "token_ids": ["nep141:eth_0xdac17f958d2ee523a2206206994597c13d831ec7"],
                    "amounts": ["1000000"],
                    "memo": "bridge-out",
                }
            ],
        })
        result = decode_log_line(log, executor_id="intents.near")
        assert len(result) == 1
        item = result[0]
        assert isinstance(item, MtWithdrawItem)
        assert item.account_id == "user.near"
        assert item.intent_hash == "someHash"
        assert item.token == "v2.omni.hot.tg"
        assert item.receiver_id == "0xabc123"
        assert item.token_ids == ["nep141:eth_0xdac17f958d2ee523a2206206994597c13d831ec7"]
        assert item.amounts == [1000000]
        assert item.memo == "bridge-out"
        assert item.version == "0.4.3"
        assert item.executor_id == "intents.near"

    def test_multiple_token_ids(self):
        log = "EVENT_JSON:" + json.dumps({
            "standard": "dip4",
            "version": "0.4.3",
            "event": "mt_withdraw",
            "data": [
                {
                    "account_id": "user.near",
                    "token": "v2.omni.hot.tg",
                    "receiver_id": "0xabc",
                    "token_ids": ["tid1", "tid2"],
                    "amounts": ["100", "200"],
                }
            ],
        })
        result = decode_log_line(log, executor_id="intents.near")
        item = result[0]
        assert item.token_ids == ["tid1", "tid2"]
        assert item.amounts == [100, 200]


class TestNativeWithdraw:
    def test_neartoken_dict_format(self):
        log = "EVENT_JSON:" + json.dumps({
            "standard": "dip4",
            "version": "0.4.3",
            "event": "native_withdraw",
            "data": [
                {
                    "intent_hash": "someHash",
                    "account_id": "user.near",
                    "receiver_id": "user.near",
                    "amount": {"amount": 1000000000000000000000000},
                }
            ],
        })
        result = decode_log_line(log, executor_id="intents.near")
        assert len(result) == 1
        item = result[0]
        assert isinstance(item, NativeWithdrawItem)
        assert item.account_id == "user.near"
        assert item.intent_hash == "someHash"
        assert item.receiver_id == "user.near"
        assert item.amount_yocto == 1000000000000000000000000
        assert item.version == "0.4.3"
        assert item.executor_id == "intents.near"

    def test_integer_amount_format(self):
        log = "EVENT_JSON:" + json.dumps({
            "standard": "dip4",
            "version": "0.4.3",
            "event": "native_withdraw",
            "data": [
                {
                    "account_id": "user.near",
                    "receiver_id": "user.near",
                    "amount": 1000000000000000000000000,
                }
            ],
        })
        result = decode_log_line(log, executor_id="intents.near")
        assert result[0].amount_yocto == 1000000000000000000000000


class TestFeeChanged:
    def test_basic(self):
        log = "EVENT_JSON:" + json.dumps({
            "standard": "dip4",
            "version": "0.3.0",
            "event": "fee_changed",
            "data": {"old_fee": 1, "new_fee": 2},
        })
        result = decode_log_line(log, executor_id="intents.near")
        assert isinstance(result, list)
        assert len(result) == 1
        item = result[0]
        assert isinstance(item, FeeChangedItem)
        assert item.old_fee_pips == 1
        assert item.new_fee_pips == 2
        assert item.version == "0.3.0"
        assert item.executor_id == "intents.near"


class TestFeeCollectorChanged:
    def test_basic(self):
        log = "EVENT_JSON:" + json.dumps({
            "standard": "dip4",
            "version": "0.3.0",
            "event": "fee_collector_changed",
            "data": {
                "old_fee_collector": "old.sputnik-dao.near",
                "new_fee_collector": "new.sputnik-dao.near",
            },
        })
        result = decode_log_line(log, executor_id="intents.near")
        assert len(result) == 1
        item = result[0]
        assert isinstance(item, FeeCollectorChangedItem)
        assert item.old_fee_collector == "old.sputnik-dao.near"
        assert item.new_fee_collector == "new.sputnik-dao.near"
        assert item.version == "0.3.0"
        assert item.executor_id == "intents.near"


class TestDecodeReceiptLogs:
    def test_filters_mixed_logs(self):
        logs = [
            "not an event",
            'EVENT_JSON:{"standard":"nep171","version":"1.0.0","event":"nft_mint","data":[]}',
            "EVENT_JSON:" + json.dumps({
                "standard": "dip4",
                "version": "0.4.3",
                "event": "token_diff",
                "data": [{"account_id": "x.near", "diff": {"nep141:usdc.near": "-1"}, "fees_collected": {}}],
            }),
        ]
        result = decode_receipt_logs(logs, executor_id="intents.near")
        assert len(result) == 1
        assert isinstance(result[0], TokenDiffItem)

    def test_returns_empty_for_no_relevant_logs(self):
        logs = ["random", "logs"]
        result = decode_receipt_logs(logs, executor_id="intents.near")
        assert result == []

    def test_context_fields_propagated(self):
        logs = [
            "EVENT_JSON:" + json.dumps({
                "standard": "dip4",
                "version": "0.4.3",
                "event": "token_diff",
                "data": [{"account_id": "x.near", "diff": {"nep141:usdc.near": "-1"}, "fees_collected": {}}],
            })
        ]
        result = decode_receipt_logs(
            logs,
            executor_id="intents.near",
            block_height=999,
            block_timestamp_ns=1700000000000000000,
            tx_hash="txABC",
            receipt_id="rcptXYZ",
        )
        item = result[0]
        assert item.block_height == 999
        assert item.block_timestamp_ns == 1700000000000000000
        assert item.tx_hash == "txABC"
        assert item.receipt_id == "rcptXYZ"

    def test_multiple_different_event_types_in_one_receipt(self):
        logs = [
            "EVENT_JSON:" + json.dumps({
                "standard": "dip4",
                "version": "0.4.3",
                "event": "token_diff",
                "data": [{"account_id": "user.near", "diff": {"nep141:usdc.near": "-100"}, "fees_collected": {"nep141:usdc.near": "1"}}],
            }),
            "EVENT_JSON:" + json.dumps({
                "standard": "dip4",
                "version": "0.4.3",
                "event": "intents_executed",
                "data": [{"intent_hash": "hashABC", "account_id": "user.near", "nonce": "nonceXYZ"}],
            }),
            "EVENT_JSON:" + json.dumps({
                "standard": "dip4",
                "version": "0.4.3",
                "event": "ft_withdraw",
                "data": [{"account_id": "user.near", "token": "usdc.near", "receiver_id": "user.near", "amount": "99"}],
            }),
        ]
        result = decode_receipt_logs(logs, executor_id="intents.near")
        assert len(result) == 3
        assert isinstance(result[0], TokenDiffItem)
        assert isinstance(result[1], IntentsExecutedItem)
        assert isinstance(result[2], FtWithdrawItem)


class TestMalformedInput:
    def test_invalid_json_raises_decode_error(self):
        log = "EVENT_JSON:{not valid json}"
        with pytest.raises(DecodeError, match="Invalid JSON"):
            decode_log_line(log, executor_id="intents.near")

    def test_data_wrong_type_raises_decode_error(self):
        log = "EVENT_JSON:" + json.dumps({
            "standard": "dip4",
            "version": "0.4.3",
            "event": "token_diff",
            "data": "should be a list",
        })
        with pytest.raises(DecodeError, match="must be a list"):
            decode_log_line(log, executor_id="intents.near")

    def test_missing_account_id_raises_decode_error(self):
        log = "EVENT_JSON:" + json.dumps({
            "standard": "dip4",
            "version": "0.4.3",
            "event": "token_diff",
            "data": [{"diff": {"nep141:usdc.near": "-1"}, "fees_collected": {}}],
        })
        with pytest.raises(DecodeError, match="account_id"):
            decode_log_line(log, executor_id="intents.near")

    def test_item_not_dict_raises_decode_error(self):
        log = "EVENT_JSON:" + json.dumps({
            "standard": "dip4",
            "version": "0.4.3",
            "event": "token_diff",
            "data": ["not a dict"],
        })
        with pytest.raises(DecodeError, match="must be a dict"):
            decode_log_line(log, executor_id="intents.near")
