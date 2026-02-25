import pandas as pd

from accrue.datatools.transformer.interface import Transformer


class PaymentEventsTransformer(Transformer):
    """
    Bronze payment_events → Silver payment_events_clean.

    Cleaning steps:
    1. Drop exact byte-for-byte duplicate rows (META_DATA_UUID match).
    2. Deduplicate on `id` — keep the row with the latest created_at.
       (handles rows that arrive out-of-order at the Bronze level or
       retry-inserted with the same event id)
    3. Add `report_date` (date portion of created_at).

    Note: out-of-order events (CAPTURED arrives before AUTHORIZED) are NOT
    filtered out here — they are legitimate events with different IDs and
    different timestamps. The Gold layer handles ordering semantics.
    """

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._drop_exact_duplicates(df)
        df = self._dedup_keep_latest(df, pk_col="id", ts_col="created_at")
        df = self._add_report_date(df, ts_col="created_at")
        return df

    def validate(self, df: pd.DataFrame) -> None:
        # id must be unique
        if df["id"].duplicated().any():
            raise ValueError("PaymentEventsTransformer: duplicate ids found after dedup.")
        # amount must be non-negative
        if (df["amount"] < 0).any():
            raise ValueError("PaymentEventsTransformer: negative amount found.")
        # event_type must be within allowed set
        allowed = {"AUTHORIZED", "CAPTURED", "REFUNDED", "DISPUTED"}
        bad = set(df["event_type"].unique()) - allowed
        if bad:
            raise ValueError(f"PaymentEventsTransformer: unknown event_type values: {bad}")
