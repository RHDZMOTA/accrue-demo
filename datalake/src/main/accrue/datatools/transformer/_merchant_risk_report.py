"""
Gold layer — Merchant Daily Risk Report transformer.

Reads from three Silver Delta tables and produces the
`gold/merchant_daily_risk_reports` aggregation table.

Source tables (Silver):
  - silver/payment_events_clean    → authorized / captured / refunded amounts
  - silver/checkout_payments_clean → dispute counts
  - silver/audit_logs_clean        → fraud signal counts

Output schema:
  merchant_id               TEXT
  report_date               DATE
  total_authorized_amount   NUMERIC
  total_captured_amount     NUMERIC
  total_refunded_amount     NUMERIC
  dispute_count             INT
  fraud_signal_count        INT
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from accrue.datatools.transformer.interface import MultiSourceTransformer


@dataclass
class MerchantDailyRiskReportTransformer(MultiSourceTransformer):
    """
    Multi-source Gold transformer.

    Reads from three Silver tables (in `source_tables` order):
      [0] payment_events_clean   → authorized / captured / refunded amounts
      [1] checkout_payments_clean → dispute counts
      [2] audit_logs_clean        → fraud signal counts

    Inherits `run()` from MultiSourceTransformer — no override needed.
    """

    # ------------------------------------------------------------------
    # MultiSourceTransformer contract
    # ------------------------------------------------------------------

    def transform(self, *dfs: pd.DataFrame) -> pd.DataFrame:
        """Unpack sources by position and delegate to the aggregation logic."""
        payment_events, checkout_payments, audit_logs = dfs
        return self._aggregate(payment_events, checkout_payments, audit_logs)

    def _aggregate(
        self,
        payment_events: pd.DataFrame,
        checkout_payments: pd.DataFrame,
        audit_logs: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Core aggregation logic.

        Step 1 — Payment event metrics (from payment_events_clean):
          GROUP BY (merchant_id, report_date)
          - total_authorized_amount : SUM(amount) WHERE event_type='AUTHORIZED'
          - total_captured_amount   : SUM(amount) WHERE event_type='CAPTURED'
          - total_refunded_amount   : SUM(amount) WHERE event_type='REFUNDED'

        Step 2 — Dispute count (from checkout_payments_clean):
          GROUP BY (merchant_id, report_date)
          - dispute_count : COUNT rows WHERE dispute_status IS NOT NULL

        Step 3 — Fraud signal count (from audit_logs_clean):
          GROUP BY (merchant_id, report_date)
          - fraud_signal_count : SUM(is_fraud_signal)

        Step 4 — FULL OUTER JOIN on (merchant_id, report_date), fill NaN → 0.
        """
        dims = ["merchant_id", "report_date"]

        # --- Step 1: payment event aggregations ---
        pe = payment_events.copy()
        pe["report_date"] = pd.to_datetime(pe["report_date"]).dt.normalize()

        pe_agg = self._agg_payment_events(pe, dims)


        # --- Step 2: dispute counts ---
        cp = checkout_payments.copy()
        cp["report_date"] = pd.to_datetime(cp["report_date"]).dt.normalize()

        disputed = cp[cp["dispute_status"].notna() & (cp["dispute_status"] != "")]
        cp_agg = (
            disputed.groupby(dims)
            .size()
            .reset_index(name="dispute_count")
        )

        # --- Step 3: fraud signal counts ---
        al = audit_logs.copy()
        al["report_date"] = pd.to_datetime(al["report_date"]).dt.normalize()

        al_agg = (
            al.groupby(dims)["is_fraud_signal"]
            .sum()
            .reset_index(name="fraud_signal_count")
        )

        # --- Step 4: full outer join ---
        result = pe_agg.merge(cp_agg, on=dims, how="outer")
        result = result.merge(al_agg, on=dims, how="outer")

        # Fill numeric NaN → 0 and cast to correct types
        result["total_authorized_amount"] = result["total_authorized_amount"].fillna(0)
        result["total_captured_amount"]   = result["total_captured_amount"].fillna(0)
        result["total_refunded_amount"]   = result["total_refunded_amount"].fillna(0)
        result["dispute_count"]           = result["dispute_count"].fillna(0).astype(int)
        result["fraud_signal_count"]      = result["fraud_signal_count"].fillna(0).astype(int)

        result = result.sort_values(dims).reset_index(drop=True)
        return result

    @staticmethod
    def _agg_payment_events(pe: pd.DataFrame, dims: list[str]) -> pd.DataFrame:
        """
        Aggregate payment events by (merchant_id, report_date).
        Returns a DataFrame with the correct columns even when pe is empty.
        """
        metric_cols = ["total_authorized_amount", "total_captured_amount", "total_refunded_amount"]
        if pe.empty:
            empty = pd.DataFrame(columns=dims + metric_cols)
            # Cast to correct dtypes so outer merges don't fail on dtype mismatch
            empty["report_date"] = pd.to_datetime(empty["report_date"])
            for col in metric_cols:
                empty[col] = empty[col].astype(float)
            return empty

        result = (
            pe.groupby(dims)
            .apply(
                lambda g: pd.Series({
                    "total_authorized_amount": g.loc[g["event_type"] == "AUTHORIZED", "amount"].sum(),
                    "total_captured_amount":   g.loc[g["event_type"] == "CAPTURED",    "amount"].sum(),
                    "total_refunded_amount":   g.loc[g["event_type"] == "REFUNDED",    "amount"].sum(),
                }),
                include_groups=False,
            )
            .reset_index()
        )
        return result


    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self, df: pd.DataFrame) -> None:
        """Post-aggregation sanity checks."""
        required = {
            "merchant_id", "report_date",
            "total_authorized_amount", "total_captured_amount",
            "total_refunded_amount", "dispute_count", "fraud_signal_count",
        }
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"MerchantDailyRiskReportTransformer: missing columns: {missing}")

        # No duplicate (merchant_id, report_date) pairs
        if df.duplicated(subset=["merchant_id", "report_date"]).any():
            raise ValueError(
                "MerchantDailyRiskReportTransformer: duplicate (merchant_id, report_date) found."
            )

        # All amounts must be non-negative
        for col in ("total_authorized_amount", "total_captured_amount", "total_refunded_amount"):
            if (df[col] < 0).any():
                raise ValueError(f"MerchantDailyRiskReportTransformer: negative {col} found.")

        # Counts must be non-negative integers
        for col in ("dispute_count", "fraud_signal_count"):
            if (df[col] < 0).any():
                raise ValueError(f"MerchantDailyRiskReportTransformer: negative {col} found.")
