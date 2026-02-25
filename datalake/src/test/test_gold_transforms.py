"""
Unit tests for the Gold layer — MerchantDailyRiskReportTransformer.

Pure pandas — no Delta Lake or Postgres required.
Tests validate all metric computations and edge cases:
  - Happy path (base data)
  - Partial captures (multiple CAPTURED events on same day)
  - Out-of-order events (CAPTURED before AUTHORIZED)
  - Duplicates already removed by Silver (shouldn't affect Gold totals)
  - Fraud signals counted independently per day
  - Disputes counted from checkout_payments dispute_status
  - Merchant/date cross-product handled via outer join (no phantom rows)
"""
import pytest
import pandas as pd
from datetime import date

from accrue.datatools.transformer._merchant_risk_report import MerchantDailyRiskReportTransformer
from accrue.datatools.dao.service._delta import DeltaService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _svc() -> DeltaService:
    return DeltaService.__new__(DeltaService)


def _transformer() -> MerchantDailyRiskReportTransformer:
    svc = _svc()
    return MerchantDailyRiskReportTransformer(
        source_tables=[
            "silver/payment_events_clean",
            "silver/checkout_payments_clean",
            "silver/audit_logs_clean",
        ],
        target_table="gold/merchant_daily_risk_reports",
        source_service=svc,
        target_service=svc,
    )


def _pe(*rows) -> pd.DataFrame:
    """payment_events_clean stub: (merchant_id, event_type, amount, report_date)"""
    cols = ["id", "merchant_id", "event_type", "amount", "created_at", "report_date"]
    data = [
        (f"evt_{i}", r[0], r[1], r[2], "2026-01-01 10:00:00", r[3])
        for i, r in enumerate(rows)
    ]
    return pd.DataFrame(data, columns=cols)


def _cp(*rows) -> pd.DataFrame:
    """checkout_payments_clean stub: (merchant_id, dispute_status, report_date)"""
    cols = ["id", "merchant_id", "amount", "captured_amount", "refund_amount",
            "dispute_status", "created_at", "report_date"]
    data = [
        (f"cp_{i}", r[0], 100, 100, 0, r[1], "2026-01-01 10:00:00", r[2])
        for i, r in enumerate(rows)
    ]
    return pd.DataFrame(data, columns=cols)


def _al(*rows) -> pd.DataFrame:
    """audit_logs_clean stub: (merchant_id, is_fraud_signal, report_date)"""
    cols = ["id", "merchant_id", "action", "created_at", "is_fraud_signal", "report_date"]
    data = [
        (f"log_{i}", r[0], "FRAUD_FLAGGED" if r[1] else "REVIEW_COMPLETED",
         "2026-01-01 12:00:00", r[1], r[2])
        for i, r in enumerate(rows)
    ]
    return pd.DataFrame(data, columns=cols)


def _row(result: pd.DataFrame, merchant: str, dt: str) -> pd.Series:
    mask = (result["merchant_id"] == merchant) & (
        result["report_date"].astype(str).str.startswith(dt)
    )
    rows = result[mask]
    assert len(rows) == 1, f"Expected 1 row for ({merchant}, {dt}), found {len(rows)}"
    return rows.iloc[0]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMerchantDailyRiskReportTransformer:

    def _t(self) -> MerchantDailyRiskReportTransformer:
        return _transformer()

    # -- Happy path ----------------------------------------------------------

    def test_happy_path_base_data(self):
        """Base scenario: one merchant, two events, no disputes, one fraud signal."""
        pe = _pe(
            ("A", "AUTHORIZED", 100, "2026-01-01"),
            ("A", "CAPTURED",   100, "2026-01-01"),
        )
        cp = _cp(("A", None, "2026-01-01"))
        al = _al(("A", True, "2026-01-01"))

        result = self._t()._aggregate(pe, cp, al)
        row = _row(result, "A", "2026-01-01")

        assert row["total_authorized_amount"] == 100
        assert row["total_captured_amount"]   == 100
        assert row["total_refunded_amount"]   == 0
        assert row["dispute_count"]           == 0   # None dispute_status → not disputed
        assert row["fraud_signal_count"]      == 1

    # -- Multiple merchants --------------------------------------------------

    def test_two_merchants_independent(self):
        """Two merchants should produce two independent rows."""
        pe = _pe(
            ("A", "AUTHORIZED", 100, "2026-01-01"),
            ("B", "AUTHORIZED", 200, "2026-01-01"),
        )
        cp = _cp()
        al = _al()

        result = self._t()._aggregate(pe, cp, al)
        assert len(result) == 2
        assert _row(result, "A", "2026-01-01")["total_authorized_amount"] == 100
        assert _row(result, "B", "2026-01-01")["total_authorized_amount"] == 200

    # -- Partial captures ----------------------------------------------------

    def test_partial_captures_amounts_sum(self):
        """Multiple CAPTURED events on same day for same merchant sum correctly."""
        pe = _pe(
            ("A", "AUTHORIZED", 150, "2026-01-02"),
            ("A", "CAPTURED",    50, "2026-01-02"),
            ("A", "CAPTURED",    30, "2026-01-02"),
        )
        cp = _cp()
        al = _al()

        result = self._t()._aggregate(pe, cp, al)
        row = _row(result, "A", "2026-01-02")
        assert row["total_authorized_amount"] == 150
        assert row["total_captured_amount"]   == 80   # 50 + 30

    # -- Out-of-order events -------------------------------------------------

    def test_out_of_order_events_aggregated_correctly(self):
        """CAPTURED before AUTHORIZED (different event IDs) → both counted."""
        pe = _pe(
            ("A", "CAPTURED",    100, "2026-01-03"),  # arrives first
            ("A", "AUTHORIZED",  100, "2026-01-03"),  # arrives second
        )
        cp = _cp()
        al = _al()

        result = self._t()._aggregate(pe, cp, al)
        row = _row(result, "A", "2026-01-03")
        assert row["total_authorized_amount"] == 100
        assert row["total_captured_amount"]   == 100

    # -- Refunds -------------------------------------------------------------

    def test_refunds_counted_from_payment_events(self):
        pe = _pe(
            ("A", "AUTHORIZED", 100, "2026-01-04"),
            ("A", "CAPTURED",   100, "2026-01-04"),
            ("A", "REFUNDED",    40, "2026-01-04"),
        )
        cp = _cp()
        al = _al()

        result = self._t()._aggregate(pe, cp, al)
        row = _row(result, "A", "2026-01-04")
        assert row["total_refunded_amount"] == 40

    # -- Disputes ------------------------------------------------------------

    def test_dispute_count_from_checkout_payments(self):
        """Only checkout_payments with a non-null dispute_status are counted."""
        pe = _pe()
        cp = _cp(
            ("A", "PENDING",  "2026-01-05"),
            ("A", "RESOLVED", "2026-01-05"),
            ("A", None,       "2026-01-05"),  # not disputed
        )
        al = _al()

        result = self._t()._aggregate(pe, cp, al)
        row = _row(result, "A", "2026-01-05")
        assert row["dispute_count"] == 2

    # -- Fraud signals -------------------------------------------------------

    def test_fraud_signal_count_independent(self):
        """Fraud signals counted from audit_logs regardless of payment events."""
        pe = _pe()
        cp = _cp()
        al = _al(
            ("A", True,  "2026-01-06"),
            ("A", True,  "2026-01-06"),
            ("A", False, "2026-01-06"),  # REVIEW_COMPLETED — not a fraud signal
        )

        result = self._t()._aggregate(pe, cp, al)
        row = _row(result, "A", "2026-01-06")
        assert row["fraud_signal_count"] == 2

    # -- Multi-day -----------------------------------------------------------

    def test_events_on_different_days_produce_separate_rows(self):
        pe = _pe(
            ("A", "AUTHORIZED", 100, "2026-01-01"),
            ("A", "AUTHORIZED", 200, "2026-01-02"),
        )
        cp = _cp()
        al = _al()

        result = self._t()._aggregate(pe, cp, al)
        assert len(result) == 2
        assert _row(result, "A", "2026-01-01")["total_authorized_amount"] == 100
        assert _row(result, "A", "2026-01-02")["total_authorized_amount"] == 200

    # -- Outer join / no phantom zeros ---------------------------------------

    def test_fraud_without_payments_still_produces_row(self):
        """A merchant with only fraud signals (no payment events) still has a row."""
        pe = _pe()
        cp = _cp()
        al = _al(("B", True, "2026-01-07"))

        result = self._t()._aggregate(pe, cp, al)
        row = _row(result, "B", "2026-01-07")
        assert row["fraud_signal_count"]      == 1
        assert row["total_authorized_amount"] == 0
        assert row["total_captured_amount"]   == 0

    # -- Validation ----------------------------------------------------------

    def test_validate_raises_on_duplicate_merchant_date(self):
        df = pd.DataFrame([
            {"merchant_id": "A", "report_date": pd.Timestamp("2026-01-01"),
             "total_authorized_amount": 100, "total_captured_amount": 100,
             "total_refunded_amount": 0, "dispute_count": 0, "fraud_signal_count": 0},
            {"merchant_id": "A", "report_date": pd.Timestamp("2026-01-01"),
             "total_authorized_amount": 50, "total_captured_amount": 50,
             "total_refunded_amount": 0, "dispute_count": 0, "fraud_signal_count": 0},
        ])
        with pytest.raises(ValueError, match="duplicate"):
            self._t().validate(df)

    def test_validate_raises_on_negative_amount(self):
        df = pd.DataFrame([{
            "merchant_id": "A", "report_date": pd.Timestamp("2026-01-01"),
            "total_authorized_amount": -1, "total_captured_amount": 0,
            "total_refunded_amount": 0, "dispute_count": 0, "fraud_signal_count": 0,
        }])
        with pytest.raises(ValueError, match="negative total_authorized_amount"):
            self._t().validate(df)
