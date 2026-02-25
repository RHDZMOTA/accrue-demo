"""
Unit tests for Silver layer transforms.

These tests run purely in-memory (pandas DataFrames) — no Delta Lake or
Postgres required. They verify the transform logic for all edge cases
mentioned in the challenge: duplicates, out-of-order events, partial
captures, and fraud signals.
"""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, date

from accrue.datatools.transformer._payment_events import PaymentEventsTransformer
from accrue.datatools.transformer._checkout_payments import CheckoutPaymentsTransformer
from accrue.datatools.transformer._audit_logs import AuditLogsTransformer
from accrue.datatools.dao.service._delta import DeltaService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_svc() -> DeltaService:
    """We never call read/write in unit tests; service is just a placeholder."""
    return DeltaService.__new__(DeltaService)


def _pmt_events(*rows) -> pd.DataFrame:
    """Build a payment_events DataFrame from (id, merchant_id, event_type, amount, created_at) tuples."""
    cols = ["id", "merchant_id", "event_type", "amount", "created_at"]
    return pd.DataFrame(list(rows), columns=cols)


def _checkout(*rows) -> pd.DataFrame:
    """Build a checkout_payments DataFrame."""
    cols = ["id", "merchant_id", "amount", "captured_amount", "refund_amount", "dispute_status", "created_at"]
    return pd.DataFrame(list(rows), columns=cols)


def _audit(*rows) -> pd.DataFrame:
    """Build an audit_logs DataFrame."""
    cols = ["id", "merchant_id", "action", "created_at"]
    return pd.DataFrame(list(rows), columns=cols)


def _transformer(cls, **kwargs):
    svc = _make_svc()
    return cls(source_table="", target_table="", source_service=svc, target_service=svc, **kwargs)


# ---------------------------------------------------------------------------
# PaymentEventsTransformer tests
# ---------------------------------------------------------------------------

class TestPaymentEventsTransformer:

    def _t(self):
        return _transformer(PaymentEventsTransformer)

    def test_happy_path_no_changes(self):
        df = _pmt_events(
            ("evt_1", "A", "AUTHORIZED", 100, "2026-01-01 10:00:00"),
            ("evt_2", "A", "CAPTURED",   100, "2026-01-01 10:05:00"),
        )
        result = self._t().transform(df)
        assert len(result) == 2
        assert "report_date" in result.columns

    def test_exact_duplicate_row_removed(self):
        """Same META_DATA_UUID → only one row survives."""
        df = _pmt_events(
            ("evt_1", "A", "AUTHORIZED", 100, "2026-01-01 10:00:00"),
            ("evt_1", "A", "AUTHORIZED", 100, "2026-01-01 10:00:00"),  # exact dup
        )
        # Simulate META_DATA_UUID column as Bronze would add it
        df["META_DATA_UUID"] = "same-uuid"
        result = self._t().transform(df)
        assert len(result) == 1

    def test_duplicate_id_keeps_latest(self):
        """Two rows with same id but different timestamps → keep latest."""
        df = _pmt_events(
            ("evt_2", "A", "CAPTURED", 100, "2026-01-01 10:05:00"),
            ("evt_2", "A", "CAPTURED", 100, "2026-01-01 10:04:00"),  # older, should be dropped
        )
        result = self._t().transform(df)
        assert len(result) == 1
        assert str(result.iloc[0]["created_at"]) >= "2026-01-01 10:05:00"

    def test_out_of_order_events_both_kept(self):
        """CAPTURED before AUTHORIZED — both have distinct IDs → both survive."""
        df = _pmt_events(
            ("evt_o1", "A", "CAPTURED",    100, "2026-01-03 08:00:00"),
            ("evt_o2", "A", "AUTHORIZED",  100, "2026-01-03 08:05:00"),
        )
        result = self._t().transform(df)
        assert len(result) == 2

    def test_partial_captures_both_kept(self):
        """Multiple CAPTURED events for same merchant with distinct IDs → both survive."""
        df = _pmt_events(
            ("evt_p1", "A", "AUTHORIZED", 150, "2026-01-02 09:00:00"),
            ("evt_p2", "A", "CAPTURED",    50, "2026-01-02 09:10:00"),
            ("evt_p3", "A", "CAPTURED",    30, "2026-01-02 09:15:00"),
        )
        result = self._t().transform(df)
        assert len(result) == 3
        assert result[result["event_type"] == "CAPTURED"]["amount"].sum() == 80

    def test_report_date_derived_from_created_at(self):
        df = _pmt_events(("evt_1", "A", "AUTHORIZED", 100, "2026-01-05 22:30:00"))
        result = self._t().transform(df)
        assert result.iloc[0]["report_date"].date() == date(2026, 1, 5)

    def test_validate_raises_on_negative_amount(self):
        df = _pmt_events(("evt_1", "A", "AUTHORIZED", -5, "2026-01-01 10:00:00"))
        df["report_date"] = pd.Timestamp("2026-01-01")
        with pytest.raises(ValueError, match="negative amount"):
            self._t().validate(df)

    def test_validate_raises_on_unknown_event_type(self):
        df = _pmt_events(("evt_1", "A", "SETTLED", 100, "2026-01-01 10:00:00"))
        df["report_date"] = pd.Timestamp("2026-01-01")
        with pytest.raises(ValueError, match="unknown event_type"):
            self._t().validate(df)


# ---------------------------------------------------------------------------
# CheckoutPaymentsTransformer tests
# ---------------------------------------------------------------------------

class TestCheckoutPaymentsTransformer:

    def _t(self):
        return _transformer(CheckoutPaymentsTransformer)

    def test_happy_path(self):
        df = _checkout(("cp_1", "A", 100, 100, 0, None, "2026-01-01 10:05:00"))
        result = self._t().transform(df)
        assert len(result) == 1

    def test_empty_string_dispute_status_coerced_to_none(self):
        df = _checkout(("cp_1", "A", 100, 100, 0, "", "2026-01-01 10:05:00"))
        result = self._t().transform(df)
        assert result.iloc[0]["dispute_status"] is None or pd.isna(result.iloc[0]["dispute_status"])

    def test_duplicate_id_last_write_wins(self):
        """Two rows with same id and different META_DATA_UUID → only one survives."""
        df = _checkout(
            ("cp_1", "A", 100, 100, 0, None,       "2026-01-01 10:05:00"),
            ("cp_1", "A", 100, 100, 0, "PENDING",  "2026-01-01 10:05:00"),
        )
        df["META_DATA_UUID"] = ["uuid_aaa", "uuid_zzz"]  # zzz > aaa → keep zzz
        result = self._t().transform(df)
        assert len(result) == 1
        assert result.iloc[0]["dispute_status"] == "PENDING"

    def test_report_date_added(self):
        df = _checkout(("cp_1", "A", 100, 100, 0, None, "2026-01-07 14:00:00"))
        result = self._t().transform(df)
        assert result.iloc[0]["report_date"].date() == date(2026, 1, 7)

    def test_validate_raises_on_over_captured(self):
        df = _checkout(("cp_1", "A", 100, 150, 0, None, "2026-01-01 10:05:00"))
        df["report_date"] = pd.Timestamp("2026-01-01")
        with pytest.raises(ValueError, match="captured_amount > amount"):
            self._t().validate(df)


# ---------------------------------------------------------------------------
# AuditLogsTransformer tests
# ---------------------------------------------------------------------------

class TestAuditLogsTransformer:

    def _t(self):
        return _transformer(AuditLogsTransformer)

    def test_fraud_signal_flag_set(self):
        df = _audit(
            ("log_1", "A", "FRAUD_FLAGGED",    "2026-01-01 12:00:00"),
            ("log_2", "B", "REVIEW_COMPLETED", "2026-01-01 12:00:00"),
        )
        result = self._t().transform(df)
        assert result.loc[result["id"] == "log_1", "is_fraud_signal"].values[0] == True
        assert result.loc[result["id"] == "log_2", "is_fraud_signal"].values[0] == False

    def test_duplicate_id_keeps_latest(self):
        df = _audit(
            ("log_f1", "A", "FRAUD_FLAGGED", "2026-01-02 10:00:00"),
            ("log_f1", "A", "FRAUD_FLAGGED", "2026-01-02 09:55:00"),  # older dup
        )
        result = self._t().transform(df)
        assert len(result) == 1

    def test_multiple_fraud_signals_different_ids_all_kept(self):
        """Each fraud signal has its own id → all survive deduplication."""
        df = _audit(
            ("log_f1", "A", "FRAUD_FLAGGED", "2026-01-02 10:00:00"),
            ("log_f2", "A", "FRAUD_FLAGGED", "2026-01-02 10:05:00"),
        )
        result = self._t().transform(df)
        assert len(result) == 2
        assert result["is_fraud_signal"].all()

    def test_report_date_added(self):
        df = _audit(("log_1", "A", "FRAUD_FLAGGED", "2026-01-02 10:00:00"))
        result = self._t().transform(df)
        assert result.iloc[0]["report_date"].date() == date(2026, 1, 2)

    def test_validate_raises_on_unknown_action(self):
        df = _audit(("log_1", "A", "UNKNOWN_ACTION", "2026-01-01 12:00:00"))
        df["is_fraud_signal"] = False
        df["report_date"] = pd.Timestamp("2026-01-01")
        with pytest.raises(ValueError, match="unknown action"):
            self._t().validate(df)
