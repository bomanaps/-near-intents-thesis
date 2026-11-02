import json
import os
import sys
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingest.from_dune import _timestamp_to_ns, _to_row, ingest_csv
from decoder import (
    FtWithdrawItem,
    MtWithdrawItem,
    TokenDiffItem,
    TransferItem,
)


def _base_row(**overrides) -> dict:
    base = {
        "block_height": 120000000,
        "block_time": "2026-10-01 12:00:00",
        "tx_hash": "txABC123",
        "receipt_id": "rcptXYZ456",
        "executor_account_id": "intents.near",
        "log": "",
    }
    return {**base, **overrides}


def _write_csv(rows: list[dict], tmp_path: Path, name: str = "export.csv") -> Path:
    path = tmp_path / name
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _token_diff_log(**data_overrides) -> str:
    data = {
        "account_id": "user.near",
        "diff": {"nep141:usdc.near": "-1000000"},
        "fees_collected": {"nep141:usdc.near": "100"},
    }
    data.update(data_overrides)
    return "EVENT_JSON:" + json.dumps(
        {"standard": "dip4", "version": "0.4.3", "event": "token_diff", "data": [data]}
    )


def _ft_withdraw_log() -> str:
    return "EVENT_JSON:" + json.dumps({
        "standard": "dip4",
        "version": "0.4.3",
        "event": "ft_withdraw",
        "data": [{"account_id": "user.near", "token": "usdc.near",
                  "receiver_id": "wallet.near", "amount": "999"}],
    })


def _token_diff_item(**overrides) -> TokenDiffItem:
    defaults = dict(
        account_id="user.near",
        intent_hash=None,
        diff={"nep141:usdc.near": -1000000},
        fees_collected={"nep141:usdc.near": 100},
        memo=None,
        referral=None,
        version="0.4.3",
        block_height=None,
        block_timestamp_ns=None,
        tx_hash=None,
        receipt_id=None,
        executor_id="intents.near",
    )
    return TokenDiffItem(**{**defaults, **overrides})


class TestToRow:
    def test_dict_fields_serialized_to_json_string(self):
        row = _to_row(_token_diff_item())
        assert isinstance(row["diff"], str)
        assert json.loads(row["diff"]) == {"nep141:usdc.near": -1000000}
        assert isinstance(row["fees_collected"], str)
        assert json.loads(row["fees_collected"]) == {"nep141:usdc.near": 100}

    def test_list_fields_on_mt_withdraw_serialized(self):
        item = MtWithdrawItem(
            account_id="user.near",
            intent_hash=None,
            token="v2.omni.hot.tg",
            receiver_id="0xabc",
            token_ids=["tid1", "tid2"],
            amounts=[100, 200],
            memo=None,
            version="0.4.3",
            block_height=None,
            block_timestamp_ns=None,
            tx_hash=None,
            receipt_id=None,
            executor_id="intents.near",
        )
        row = _to_row(item)
        assert json.loads(row["token_ids"]) == ["tid1", "tid2"]
        assert json.loads(row["amounts"]) == [100, 200]

    def test_tokens_dict_on_transfer_serialized(self):
        item = TransferItem(
            account_id="sender.near",
            intent_hash=None,
            receiver_id="receiver.near",
            tokens={"nep141:usdc.near": 5000000},
            memo=None,
            version="0.4.3",
            block_height=None,
            block_timestamp_ns=None,
            tx_hash=None,
            receipt_id=None,
            executor_id="intents.near",
        )
        row = _to_row(item)
        assert isinstance(row["tokens"], str)
        assert json.loads(row["tokens"]) == {"nep141:usdc.near": 5000000}

    def test_scalar_fields_pass_through_unchanged(self):
        item = FtWithdrawItem(
            account_id="user.near",
            intent_hash="hashABC",
            token="usdc.near",
            receiver_id="wallet.near",
            amount=1000000,
            memo=None,
            version="0.4.3",
            block_height=120000000,
            block_timestamp_ns=1700000000000000000,
            tx_hash="txABC",
            receipt_id="rcptXYZ",
            executor_id="intents.near",
        )
        row = _to_row(item)
        assert row["account_id"] == "user.near"
        assert row["amount"] == 1000000
        assert row["block_height"] == 120000000
        assert row["tx_hash"] == "txABC"
        assert row["intent_hash"] == "hashABC"
        assert row["memo"] is None

    def test_empty_dicts_serialize_as_empty_json_objects(self):
        row = _to_row(_token_diff_item(diff={}, fees_collected={}))
        assert row["diff"] == "{}"
        assert row["fees_collected"] == "{}"


class TestTimestampToNs:
    def test_float_nan_returns_none(self):
        assert _timestamp_to_ns(float("nan")) is None

    def test_pandas_nat_returns_none(self):
        assert _timestamp_to_ns(pd.NaT) is None

    def test_tz_naive_string_localized_to_utc(self):
        result = _timestamp_to_ns("2026-01-01 00:00:00")
        expected = int(pd.Timestamp("2026-01-01 00:00:00", tz="UTC").value)
        assert result == expected

    def test_tz_aware_utc_string_parsed_correctly(self):
        result = _timestamp_to_ns("2026-01-01 00:00:00+00:00")
        expected = int(pd.Timestamp("2026-01-01 00:00:00+00:00").value)
        assert result == expected

    def test_tz_naive_and_tz_aware_same_instant_agree(self):
        assert _timestamp_to_ns("2026-06-15 08:30:00") == _timestamp_to_ns("2026-06-15 08:30:00+00:00")

    def test_returns_integer(self):
        assert isinstance(_timestamp_to_ns("2026-01-01 00:00:00"), int)


class TestIngestCsvColumns:
    def test_missing_required_column_raises_value_error(self, tmp_path):
        path = _write_csv([{"wrong_col": "x"}], tmp_path)
        with pytest.raises(ValueError, match="Columns not found in CSV"):
            ingest_csv(path, tmp_path / "out")

    def test_column_map_override_accepted(self, tmp_path):
        out = tmp_path / "out"
        df = pd.DataFrame([{
            "block_height": 120000000,
            "block_time": "2026-10-01 12:00:00",
            "tx_hash": "tx1",
            "receipt_id": "rcpt1",
            "contract_id": "intents.near",
            "log": _token_diff_log(),
        }])
        path = tmp_path / "custom.csv"
        df.to_csv(path, index=False)
        counts = ingest_csv(path, out, column_map={"executor_id": "contract_id"})
        assert counts["token_diff"] == 1

    def test_column_map_pointing_to_absent_column_raises(self, tmp_path):
        path = _write_csv([_base_row(log=_token_diff_log())], tmp_path)
        with pytest.raises(ValueError, match="Columns not found in CSV"):
            ingest_csv(path, tmp_path / "out", column_map={"executor_id": "no_such_column"})

    def test_out_dir_created_recursively_if_absent(self, tmp_path):
        deep = tmp_path / "a" / "b" / "c"
        ingest_csv(_write_csv([_base_row(log="irrelevant")], tmp_path), deep)
        assert deep.is_dir()


class TestIngestCsvFiltering:
    def test_non_string_log_skipped(self, tmp_path):
        path = _write_csv([_base_row(log=float("nan"))], tmp_path)
        counts = ingest_csv(path, tmp_path / "out")
        assert counts["token_diff"] == 0

    def test_non_intents_executor_skipped(self, tmp_path):
        path = _write_csv(
            [_base_row(executor_account_id="other.near", log=_token_diff_log())], tmp_path
        )
        counts = ingest_csv(path, tmp_path / "out")
        assert counts["token_diff"] == 0

    def test_defuse_alpha_near_executor_accepted(self, tmp_path):
        path = _write_csv(
            [_base_row(executor_account_id="defuse-alpha.near", log=_token_diff_log())], tmp_path
        )
        counts = ingest_csv(path, tmp_path / "out")
        assert counts["token_diff"] == 1

    def test_non_dip4_standard_skipped(self, tmp_path):
        log = "EVENT_JSON:" + json.dumps(
            {"standard": "nep171", "version": "1.0.0", "event": "nft_mint", "data": []}
        )
        path = _write_csv([_base_row(log=log)], tmp_path)
        counts = ingest_csv(path, tmp_path / "out")
        assert counts["token_diff"] == 0

    def test_all_zero_counts_when_no_relevant_logs(self, tmp_path):
        path = _write_csv([_base_row(log="just a plain log")], tmp_path)
        counts = ingest_csv(path, tmp_path / "out")
        for event_type in ("token_diff", "intents_executed", "transfer",
                           "ft_withdraw", "mt_withdraw", "native_withdraw",
                           "fee_changed", "fee_collector_changed"):
            assert counts[event_type] == 0


class TestIngestCsvOutput:
    def test_token_diff_count_and_file_written(self, tmp_path):
        out = tmp_path / "out"
        ingest_csv(_write_csv([_base_row(log=_token_diff_log())], tmp_path), out)
        assert (out / "token_diff.parquet").exists()

    def test_parquet_row_fields_match_decoded_event(self, tmp_path):
        out = tmp_path / "out"
        ingest_csv(
            _write_csv(
                [_base_row(log=_token_diff_log(), tx_hash="txDEF",
                           receipt_id="rcptABC", block_height=130000000)],
                tmp_path,
            ),
            out,
        )
        df = pq.read_table(out / "token_diff.parquet").to_pandas()
        assert len(df) == 1
        row = df.iloc[0]
        assert row["account_id"] == "user.near"
        assert row["tx_hash"] == "txDEF"
        assert row["receipt_id"] == "rcptABC"
        assert row["block_height"] == 130000000
        assert json.loads(row["diff"]) == {"nep141:usdc.near": -1000000}
        assert json.loads(row["fees_collected"]) == {"nep141:usdc.near": 100}

    def test_block_timestamp_stored_as_nanoseconds(self, tmp_path):
        out = tmp_path / "out"
        ts = "2026-10-01 00:00:00"
        ingest_csv(_write_csv([_base_row(log=_token_diff_log(), block_time=ts)], tmp_path), out)
        df = pq.read_table(out / "token_diff.parquet").to_pandas()
        expected_ns = int(pd.Timestamp(ts, tz="UTC").value)
        assert df.iloc[0]["block_timestamp_ns"] == expected_ns

    def test_null_tx_hash_stored_as_null_in_parquet(self, tmp_path):
        out = tmp_path / "out"
        ingest_csv(
            _write_csv([_base_row(log=_token_diff_log(), tx_hash=float("nan"))], tmp_path), out
        )
        df = pq.read_table(out / "token_diff.parquet").to_pandas()
        assert df.iloc[0]["tx_hash"] is None or pd.isna(df.iloc[0]["tx_hash"])

    def test_multiple_event_types_routed_to_separate_files(self, tmp_path):
        out = tmp_path / "out"
        counts = ingest_csv(
            _write_csv(
                [_base_row(log=_token_diff_log()), _base_row(log=_ft_withdraw_log())], tmp_path
            ),
            out,
        )
        assert counts["token_diff"] == 1
        assert counts["ft_withdraw"] == 1
        assert (out / "token_diff.parquet").exists()
        assert (out / "ft_withdraw.parquet").exists()

    def test_multiple_data_items_in_one_log_each_become_a_row(self, tmp_path):
        out = tmp_path / "out"
        log = "EVENT_JSON:" + json.dumps({
            "standard": "dip4",
            "version": "0.4.3",
            "event": "token_diff",
            "data": [
                {"account_id": "a.near", "diff": {"nep141:usdc.near": "-100"}, "fees_collected": {}},
                {"account_id": "b.near", "diff": {"nep141:usdc.near": "99"}, "fees_collected": {}},
            ],
        })
        counts = ingest_csv(_write_csv([_base_row(log=log)], tmp_path), out)
        assert counts["token_diff"] == 2
        df = pq.read_table(out / "token_diff.parquet").to_pandas()
        assert set(df["account_id"].tolist()) == {"a.near", "b.near"}

    def test_append_new_rows_to_existing_parquet(self, tmp_path):
        out = tmp_path / "out"
        path = _write_csv([_base_row(log=_token_diff_log())], tmp_path)
        ingest_csv(path, out)
        ingest_csv(path, out)
        df = pq.read_table(out / "token_diff.parquet").to_pandas()
        assert len(df) == 2

    def test_second_run_count_reflects_only_new_rows(self, tmp_path):
        out = tmp_path / "out"
        path = _write_csv([_base_row(log=_token_diff_log())], tmp_path)
        ingest_csv(path, out)
        counts = ingest_csv(path, out)
        assert counts["token_diff"] == 1


class TestIngestCsvErrors:
    def test_decode_error_written_to_errors_parquet(self, tmp_path):
        out = tmp_path / "out"
        bad_log = "EVENT_JSON:{not valid json}"
        ingest_csv(_write_csv([_base_row(log=bad_log)], tmp_path), out)
        assert (out / "decode_errors.parquet").exists()
        df = pq.read_table(out / "decode_errors.parquet").to_pandas()
        assert len(df) == 1
        assert "Invalid JSON" in df.iloc[0]["error"]
        assert df.iloc[0]["log"] == bad_log

    def test_decode_error_count_included_in_return(self, tmp_path):
        out = tmp_path / "out"
        counts = ingest_csv(
            _write_csv([_base_row(log="EVENT_JSON:{bad}")], tmp_path), out
        )
        assert counts["decode_errors"] == 1

    def test_decode_error_does_not_halt_processing(self, tmp_path):
        out = tmp_path / "out"
        counts = ingest_csv(
            _write_csv(
                [_base_row(log="EVENT_JSON:{bad}"), _base_row(log=_token_diff_log())], tmp_path
            ),
            out,
        )
        assert counts["decode_errors"] == 1
        assert counts["token_diff"] == 1

    def test_errors_appended_on_successive_runs(self, tmp_path):
        out = tmp_path / "out"
        path = _write_csv([_base_row(log="EVENT_JSON:{bad}")], tmp_path)
        ingest_csv(path, out)
        ingest_csv(path, out)
        df = pq.read_table(out / "decode_errors.parquet").to_pandas()
        assert len(df) == 2
