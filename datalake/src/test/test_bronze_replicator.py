"""
Unit tests for the Bronze layer — Replicator.

All tests run purely in-memory (pandas DataFrames + mock service objects).
No Delta Lake or Postgres required.

Coverage:
  - META_DATA_UUID generation (deterministic, content-based)
  - META_KEYS_UUID generation (primary key hash)
  - Quality rule validation: not_null, unique, value_range, allowed_values
  - replicate_full(): read → validate → add metadata → write (overwrite)
  - replicate_incremental(): watermark resolution, bootstrap, upsert path
  - _resolve_watermark(): first-run (empty target) detection
"""
import uuid
from unittest.mock import MagicMock, patch, call
from dataclasses import dataclass, field

import pytest
import pandas as pd

from accrue.datatools.replicator import Replicator
from accrue.configs.contracts.interface import Contract, QualityRule, ColumnSpec, WatermarkSpec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _contract(
    table_name: str = "payment_events",
    pk_cols: list[str] | None = None,
    quality_rules: list[dict] | None = None,
) -> Contract:
    """Build a minimal Contract for testing."""
    pks = [ColumnSpec(name=c, type="TEXT") for c in (pk_cols or ["id"])]
    rules = [QualityRule(**r) for r in (quality_rules or [])]
    return Contract(
        contract_version="1.0.0",
        description="test",
        owner="test",
        tags=[],
        source_service_type="POSTGRES",
        database_schema="public",
        table_name=table_name,
        target_service_type="DELTA",
        target_layer="bronze",
        target_tablename=f"bronze/{table_name}",
        refresh_mode="incremental",
        primary_keys=pks,
        watermark=None,
        quality_rules=rules,
    )


def _mock_svc(read_return: pd.DataFrame | None = None) -> MagicMock:
    svc = MagicMock()
    if read_return is not None:
        svc.read_table.return_value = read_return
    return svc


def _replicator(
    source_df: pd.DataFrame | None = None,
    target_df: pd.DataFrame | None = None,
    contract: Contract | None = None,
) -> tuple[Replicator, MagicMock, MagicMock]:
    src = _mock_svc(source_df if source_df is not None else pd.DataFrame())
    tgt = _mock_svc(target_df if target_df is not None else pd.DataFrame())
    rep = Replicator(
        source_tablename="payment_events",
        source_service=src,
        target_tablename="bronze/payment_events",
        target_service=tgt,
        contract=contract or _contract(),
    )
    return rep, src, tgt


def _pe(*rows) -> pd.DataFrame:
    """Build a minimal payment_events DataFrame."""
    cols = ["id", "merchant_id", "event_type", "amount", "created_at"]
    return pd.DataFrame(list(rows), columns=cols)


# ---------------------------------------------------------------------------
# META_DATA_UUID / META_KEYS_UUID generation
# ---------------------------------------------------------------------------

class TestMetadataUUIDs:

    def test_uuid_columns_added(self):
        rep, _, _ = _replicator()
        df = _pe(("evt_1", "A", "AUTHORIZED", 100, "2026-01-01 10:00:00"))
        rep._add_metadata_uuids(df)
        assert "META_KEYS_UUID" in df.columns
        assert "META_DATA_UUID" in df.columns

    def test_uuid_is_deterministic(self):
        """Same row content → same UUID on every call."""
        rep, _, _ = _replicator()
        df1 = _pe(("evt_1", "A", "AUTHORIZED", 100, "2026-01-01 10:00:00"))
        df2 = _pe(("evt_1", "A", "AUTHORIZED", 100, "2026-01-01 10:00:00"))
        rep._add_metadata_uuids(df1)
        rep._add_metadata_uuids(df2)
        assert df1.iloc[0]["META_DATA_UUID"] == df2.iloc[0]["META_DATA_UUID"]
        assert df1.iloc[0]["META_KEYS_UUID"] == df2.iloc[0]["META_KEYS_UUID"]

    def test_data_uuid_changes_when_content_changes(self):
        """Different amount → different META_DATA_UUID."""
        rep, _, _ = _replicator()
        df1 = _pe(("evt_1", "A", "AUTHORIZED", 100, "2026-01-01 10:00:00"))
        df2 = _pe(("evt_1", "A", "AUTHORIZED", 999, "2026-01-01 10:00:00"))  # amount differs
        rep._add_metadata_uuids(df1)
        rep._add_metadata_uuids(df2)
        assert df1.iloc[0]["META_DATA_UUID"] != df2.iloc[0]["META_DATA_UUID"]

    def test_keys_uuid_stable_when_only_amount_changes(self):
        """META_KEYS_UUID is based on primary keys only — changes in non-PK columns don't affect it."""
        rep, _, _ = _replicator()
        df1 = _pe(("evt_1", "A", "AUTHORIZED", 100, "2026-01-01 10:00:00"))
        df2 = _pe(("evt_1", "A", "AUTHORIZED", 999, "2026-01-01 10:00:00"))  # amount differs
        rep._add_metadata_uuids(df1)
        rep._add_metadata_uuids(df2)
        assert df1.iloc[0]["META_KEYS_UUID"] == df2.iloc[0]["META_KEYS_UUID"]

    def test_empty_dataframe_no_crash(self):
        """_add_metadata_uuids on empty DataFrame is a no-op."""
        rep, _, _ = _replicator()
        df = _pe()
        rep._add_metadata_uuids(df)  # should not raise
        assert "META_KEYS_UUID" not in df.columns  # skipped for empty

    def test_uuid5_format(self):
        """Generated UUIDs must be valid UUID5 strings."""
        rep, _, _ = _replicator()
        df = _pe(("evt_1", "A", "AUTHORIZED", 100, "2026-01-01 10:00:00"))
        rep._add_metadata_uuids(df)
        uuid_str = df.iloc[0]["META_DATA_UUID"]
        parsed = uuid.UUID(uuid_str)
        assert parsed.version == 5


# ---------------------------------------------------------------------------
# Quality rule validation
# ---------------------------------------------------------------------------

class TestQualityValidation:

    def _rep_with_rules(self, rules: list[dict]) -> Replicator:
        rep, _, _ = _replicator(contract=_contract(quality_rules=rules))
        return rep

    def test_not_null_passes_clean_data(self):
        rep = self._rep_with_rules([{"rule_type": "not_null", "columns": ["id", "amount"]}])
        df = _pe(("evt_1", "A", "AUTHORIZED", 100, "2026-01-01"))
        rep._validate_quality_constraint(df)  # no exception

    def test_not_null_raises_on_null(self):
        rep = self._rep_with_rules([{"rule_type": "not_null", "columns": ["amount"]}])
        df = _pe(("evt_1", "A", "AUTHORIZED", None, "2026-01-01"))
        with pytest.raises(ValueError, match="amount.*nulls"):
            rep._validate_quality_constraint(df)

    def test_unique_passes_distinct_ids(self):
        rep = self._rep_with_rules([{"rule_type": "unique", "columns": ["id"]}])
        df = _pe(
            ("evt_1", "A", "AUTHORIZED", 100, "2026-01-01"),
            ("evt_2", "A", "CAPTURED",   100, "2026-01-01"),
        )
        rep._validate_quality_constraint(df)  # no exception

    def test_unique_raises_on_duplicate_id(self):
        rep = self._rep_with_rules([{"rule_type": "unique", "columns": ["id"]}])
        df = _pe(
            ("evt_1", "A", "AUTHORIZED", 100, "2026-01-01"),
            ("evt_1", "A", "AUTHORIZED", 100, "2026-01-01"),  # duplicate
        )
        with pytest.raises(ValueError, match="not unique"):
            rep._validate_quality_constraint(df)

    def test_value_range_passes(self):
        rep = self._rep_with_rules([{"rule_type": "value_range", "column": "amount", "min": 0}])
        df = _pe(("evt_1", "A", "AUTHORIZED", 100, "2026-01-01"))
        rep._validate_quality_constraint(df)  # no exception

    def test_value_range_raises_on_negative(self):
        rep = self._rep_with_rules([{"rule_type": "value_range", "column": "amount", "min": 0}])
        df = _pe(("evt_1", "A", "AUTHORIZED", -5, "2026-01-01"))
        with pytest.raises(ValueError, match="amount.*< 0"):
            rep._validate_quality_constraint(df)

    def test_allowed_values_passes(self):
        rep = self._rep_with_rules([
            {"rule_type": "allowed_values", "column": "event_type",
             "values": ["AUTHORIZED", "CAPTURED", "REFUNDED", "DISPUTED"]}
        ])
        df = _pe(("evt_1", "A", "AUTHORIZED", 100, "2026-01-01"))
        rep._validate_quality_constraint(df)  # no exception

    def test_allowed_values_raises_on_unknown(self):
        rep = self._rep_with_rules([
            {"rule_type": "allowed_values", "column": "event_type",
             "values": ["AUTHORIZED", "CAPTURED", "REFUNDED", "DISPUTED"]}
        ])
        df = _pe(("evt_1", "A", "SETTLED", 100, "2026-01-01"))
        with pytest.raises(ValueError, match="disallowed values"):
            rep._validate_quality_constraint(df)

    def test_no_contract_skips_validation(self):
        """Replicator without a contract never raises on bad data."""
        rep = Replicator(
            source_tablename="t", source_service=_mock_svc(),
            target_tablename="b/t", target_service=_mock_svc(),
            contract=None,
        )
        df = _pe(("evt_1", "A", "BAD_TYPE", -999, "2026-01-01"))
        rep._validate_quality_constraint(df)  # no exception


# ---------------------------------------------------------------------------
# replicate_full()
# ---------------------------------------------------------------------------

class TestReplicateFull:

    def test_writes_with_overwrite_mode(self):
        df = _pe(("evt_1", "A", "AUTHORIZED", 100, "2026-01-01"))
        rep, _, tgt = _replicator(source_df=df)
        rep.replicate_full()
        tgt.write.assert_called_once()
        _, kwargs = tgt.write.call_args
        assert kwargs.get("mode") == "overwrite" or tgt.write.call_args[0][2] == "overwrite" or \
               tgt.write.call_args.kwargs.get("mode") == "overwrite"

    def test_metadata_uuids_added_before_write(self):
        df = _pe(("evt_1", "A", "AUTHORIZED", 100, "2026-01-01"))
        rep, _, tgt = _replicator(source_df=df)
        rep.replicate_full()
        call_args = tgt.write.call_args
        written_df = call_args.kwargs["data"] if "data" in call_args.kwargs else call_args[0][1]
        assert "META_DATA_UUID" in written_df.columns
        assert "META_KEYS_UUID" in written_df.columns

    def test_quality_violation_aborts_write(self):
        rules = [{"rule_type": "not_null", "columns": ["amount"]}]
        df = _pe(("evt_1", "A", "AUTHORIZED", None, "2026-01-01"))
        rep, _, tgt = _replicator(source_df=df, contract=_contract(quality_rules=rules))
        with pytest.raises(ValueError, match="nulls"):
            rep.replicate_full()
        tgt.write.assert_not_called()

    def test_returns_dataframe(self):
        df = _pe(("evt_1", "A", "AUTHORIZED", 100, "2026-01-01"))
        rep, _, _ = _replicator(source_df=df)
        result = rep.replicate_full()
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _resolve_watermark()
# ---------------------------------------------------------------------------

class TestResolveWatermark:

    def test_returns_max_of_watermark_col(self):
        target_df = pd.DataFrame({
            "created_at": ["2026-01-01 10:00:00", "2026-01-03 12:00:00", "2026-01-02 08:00:00"],
        })
        rep, _, _ = _replicator(target_df=target_df)
        result = rep._resolve_watermark("created_at")
        assert result == "2026-01-03 12:00:00"

    def test_returns_none_when_target_empty(self):
        rep, _, _ = _replicator(target_df=pd.DataFrame())
        assert rep._resolve_watermark("created_at") is None

    def test_returns_none_when_target_read_fails(self):
        rep, _, tgt = _replicator()
        tgt.read_table.side_effect = Exception("table not found")
        assert rep._resolve_watermark("created_at") is None


# ---------------------------------------------------------------------------
# replicate_incremental()
# ---------------------------------------------------------------------------

class TestReplicateIncremental:

    def test_bootstraps_full_on_empty_target(self):
        """First run: empty target → fall back to replicate_full()."""
        source_df = _pe(("evt_1", "A", "AUTHORIZED", 100, "2026-01-01"))
        rep, src, tgt = _replicator(source_df=source_df, target_df=pd.DataFrame())
        rep.replicate_incremental(watermark_col="created_at", fail_if_not_exists=False)
        # replicate_full calls write with mode=overwrite
        tgt.write.assert_called_once()

    def test_fail_if_not_exists_raises_on_empty_target(self):
        rep, _, _ = _replicator(target_df=pd.DataFrame())
        with pytest.raises(ValueError, match="does not exist or is empty"):
            rep.replicate_incremental(watermark_col="created_at", fail_if_not_exists=True)

    def test_upserts_new_rows_when_watermark_resolved(self):
        """Subsequent runs: new rows upserted, target not overwritten."""
        target_df = pd.DataFrame({
            "id": ["evt_1"],
            "created_at": ["2026-01-01 10:00:00"],
        })
        new_rows = _pe(("evt_2", "A", "CAPTURED", 100, "2026-01-02 09:00:00"))
        rep, src, tgt = _replicator(target_df=target_df)
        src.read_incremental.return_value = new_rows
        rep.replicate_incremental(watermark_col="created_at")
        tgt.upsert.assert_called_once()

    def test_no_write_when_incremental_read_is_empty(self):
        """No new rows past watermark → no upsert."""
        target_df = pd.DataFrame({
            "id": ["evt_1"],
            "created_at": ["2026-01-01 10:00:00"],
        })
        rep, src, tgt = _replicator(target_df=target_df)
        src.read_incremental.return_value = pd.DataFrame()
        rep.replicate_incremental(watermark_col="created_at")
        tgt.upsert.assert_not_called()
        tgt.write.assert_not_called()

    def test_explicit_watermark_bypasses_target_read(self):
        """When watermark_value is provided explicitly, target is not read for watermark."""
        new_rows = _pe(("evt_2", "A", "CAPTURED", 100, "2026-01-02 09:00:00"))
        rep, src, tgt = _replicator()
        src.read_incremental.return_value = new_rows
        rep.replicate_incremental(
            watermark_col="created_at",
            watermark_value="2026-01-01 00:00:00",
        )
        # target.read_table should NOT be called for watermark resolution
        tgt.read_table.assert_not_called()
        tgt.upsert.assert_called_once()
