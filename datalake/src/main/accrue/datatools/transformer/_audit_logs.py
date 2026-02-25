import pandas as pd

from accrue.datatools.transformer.interface import Transformer


class AuditLogsTransformer(Transformer):
    """
    Bronze audit_logs → Silver audit_logs_clean.

    Cleaning steps:
    1. Drop exact byte-for-byte duplicates.
    2. Deduplicate on `id` — keep the row with the latest created_at.
    3. Add `is_fraud_signal` boolean flag (action == 'FRAUD_FLAGGED').
    4. Add `report_date` (date portion of created_at).
    """

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._drop_exact_duplicates(df)
        df = self._dedup_keep_latest(df, pk_col="id", ts_col="created_at")
        df["is_fraud_signal"] = df["action"] == "FRAUD_FLAGGED"
        df = self._add_report_date(df, ts_col="created_at")
        return df

    def validate(self, df: pd.DataFrame) -> None:
        if df["id"].duplicated().any():
            raise ValueError("AuditLogsTransformer: duplicate ids found after dedup.")
        allowed = {"FRAUD_FLAGGED", "REVIEW_COMPLETED", "DISPUTE_OPENED", "DISPUTE_RESOLVED"}
        bad = set(df["action"].unique()) - allowed
        if bad:
            raise ValueError(f"AuditLogsTransformer: unknown action values: {bad}")
