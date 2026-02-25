"""
Silver layer transform framework.

Each concrete Transformer reads a Bronze Delta table, applies table-specific
cleaning/deduplication logic, then writes the result to a Silver Delta table
(full overwrite — Silver is always recomputed from Bronze).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from accrue.datatools.dao.service._delta import DeltaService


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

@dataclass
class Transformer:
    """
    Abstract base for Bronze → Silver transforms.

    Subclasses implement `transform(df)` and optionally `validate(df)`.
    `run()` orchestrates: read → transform → validate → write.
    """
    source_table: str
    target_table: str
    source_service: "DeltaService"
    target_service: "DeltaService"

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Override in subclass. Must return a clean DataFrame."""
        raise NotImplementedError

    def validate(self, df: pd.DataFrame) -> None:
        """Override to add post-transform assertions. Raise ValueError on failure."""
        pass

    def run(self) -> pd.DataFrame:
        """Full pipeline: read Bronze → transform → validate → write Silver."""
        df = self.source_service.read_table(self.source_table)
        df = self.transform(df)
        self.validate(df)
        self.target_service.write(
            table=self.target_table,
            data=df,
            mode="overwrite",
        )
        print(f"  ✓ {self.source_table} → {self.target_table}  ({len(df)} rows)")
        return df

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _add_report_date(df: pd.DataFrame, ts_col: str = "created_at") -> pd.DataFrame:
        """Derive report_date (date only) from a timestamp column."""
        df = df.copy()
        df["report_date"] = pd.to_datetime(df[ts_col]).dt.normalize().dt.tz_localize(None)
        return df

    @staticmethod
    def _drop_exact_duplicates(df: pd.DataFrame) -> pd.DataFrame:
        """Remove rows with identical META_DATA_UUID (byte-for-byte duplicates)."""
        if "META_DATA_UUID" in df.columns:
            return df.drop_duplicates(subset=["META_DATA_UUID"])
        return df.drop_duplicates()

    @staticmethod
    def _dedup_keep_latest(df: pd.DataFrame, pk_col: str, ts_col: str) -> pd.DataFrame:
        """
        For each unique pk_col value keep only the row with the latest ts_col.
        Safe for out-of-order events: we keep both rows when they have different
        primary keys — only true duplicates (same id) are collapsed.
        """
        return (
            df.sort_values(ts_col, ascending=False)
              .drop_duplicates(subset=[pk_col], keep="first")
              .reset_index(drop=True)
        )
