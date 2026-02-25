import pandas as pd

from accrue.datatools.transformer.interface import Transformer


class CheckoutPaymentsTransformer(Transformer):
    """
    Bronze checkout_payments → Silver checkout_payments_clean.

    Cleaning steps:
    1. Drop exact byte-for-byte duplicates.
    2. Deduplicate on `id` — keep the row with the largest META_DATA_UUID
       (last-write-wins, because checkout_payments is mutable: dispute_status
       and refund_amount can be updated post-creation).
    3. Coerce empty-string dispute_status → None (NULL).
    4. Add `report_date` (date portion of created_at).
    """

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._drop_exact_duplicates(df)

        # Last-write-wins dedup: largest META_DATA_UUID acts as a logical version
        # (hash is deterministic so a changed row always gets a different hash;
        # under concurrent writes the "latest" content wins)
        if "META_DATA_UUID" in df.columns:
            df = (
                df.sort_values("META_DATA_UUID", ascending=False)
                  .drop_duplicates(subset=["id"], keep="first")
                  .reset_index(drop=True)
            )
        else:
            df = df.drop_duplicates(subset=["id"], keep="last").reset_index(drop=True)

        # Coerce empty-string dispute_status → None
        if "dispute_status" in df.columns:
            df["dispute_status"] = df["dispute_status"].replace("", None)

        df = self._add_report_date(df, ts_col="created_at")
        return df

    def validate(self, df: pd.DataFrame) -> None:
        if df["id"].duplicated().any():
            raise ValueError("CheckoutPaymentsTransformer: duplicate ids found after dedup.")
        # Partial-capture invariant: captured_amount must not exceed authorized amount
        over_captured = df["captured_amount"] > df["amount"]
        if over_captured.any():
            bad_ids = df.loc[over_captured, "id"].tolist()
            raise ValueError(
                f"CheckoutPaymentsTransformer: captured_amount > amount for ids: {bad_ids}"
            )
        if (df["refund_amount"] < 0).any():
            raise ValueError("CheckoutPaymentsTransformer: negative refund_amount found.")
