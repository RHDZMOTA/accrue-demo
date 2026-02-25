import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from accrue.datatools.dao.service.interface import ServiceInterface


@dataclass
class DeltaService(ServiceInterface):
    """
    DAO for Delta Lake tables stored on the local filesystem (or S3/GCS with
    the appropriate storage_options passed via kwargs).

    `path` is the base directory; individual tables live at `{path}/{table}`.
    Convention:
        ./datalake/layer/bronze/payment_events/
        ./datalake/layer/silver/payment_events_clean/
        ./datalake/layer/gold/merchant_daily_risk_reports/

    NOTE: The default path is cwd-relative (`./datalake/layer`). All datajobs
    must be invoked from the **project root** so that Delta tables land in the
    correct location. Override via the `DELTA_PATH` environment variable if
    running from a different working directory.
    """
    path: str = field(default_factory=lambda: os.path.abspath(os.environ.get("DELTA_PATH", "./datalake/layer")))

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @staticmethod
    def auto(**kwargs) -> "DeltaService":
        return DeltaService(**kwargs)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _table_path(self, table: str) -> str:
        """Resolve the full raw absolute path for a given table name."""
        return os.path.join(self.path, table)

    def _table_uri(self, table: str) -> str:
        """Convert the raw path to a safe file:// URI exclusively for Rust deltalake."""
        return Path(self._table_path(table)).as_uri()

    def _exists(self, table: str) -> bool:
        """Return True if the Delta table has a _delta_log directory."""
        log_dir = os.path.join(self._table_path(table), "_delta_log")
        return os.path.isdir(log_dir)

    # ------------------------------------------------------------------
    # ServiceInterface implementation
    # ------------------------------------------------------------------

    def read_table(self, table: str, query: str | None = None) -> pd.DataFrame:
        """
        Full scan of a Delta table, returned as a Pandas DataFrame.
        Optional `query` is a SQL WHERE clause fragment applied after loading.
        """
        from deltalake import DeltaTable

        dt = DeltaTable(self._table_uri(table))
        df = dt.to_pandas()
        if query:
            df = df.query(query)
        return df

    def read_incremental(
        self,
        table: str,
        watermark_col: str,
        watermark_value: str,
        overlap_interval: str | None = None,
    ) -> pd.DataFrame:
        """
        Read only rows where watermark_col > watermark_value (minus overlap_interval).
        Uses Delta's partition pruning when watermark_col is a partition column.
        """
        from deltalake import DeltaTable

        dt = DeltaTable(self._table_uri(table))
        df = dt.to_pandas()
        
        if overlap_interval:
            target_val = str(pd.to_datetime(watermark_value) - pd.Timedelta(overlap_interval))
            return df[df[watermark_col] >= target_val]
            
        return df[df[watermark_col] > watermark_value]

    # ------------------------------------------------------------------
    # Delta-specific write operations
    # ------------------------------------------------------------------

    def write(
        self,
        table: str,
        data: pd.DataFrame,
        mode: Literal["append", "overwrite", "error", "ignore"] = "append",
        partition_by: list[str] | None = None,
    ) -> None:
        """
        Write a Pandas DataFrame to a Delta table.
        - mode="append"    → adds rows
        - mode="overwrite" → replaces the table (safe for full reloads of
                             mutable tables like checkout_payments)
        """
        from deltalake import write_deltalake
        
        # Cast any object columns that are completely null to string
        # to prevent `Invalid data type for Delta Lake: Null` error
        for col in data.columns:
            if data[col].dtype == 'object' and data[col].isnull().all():
                data[col] = data[col].astype(str)

        write_deltalake(
            table_or_uri=self._table_uri(table),
            data=data,
            mode=mode,
            partition_by=partition_by or [],
        )

    def upsert(
        self,
        table: str,
        data: pd.DataFrame,
        merge_key: str,
    ) -> None:
        """
        Merge new data into an existing Delta table on `merge_key`.
        - Matching rows are updated in-place (idempotent deduplication).
        - Non-matching rows are inserted.
        Falls back to a plain write if the table does not exist yet.
        """
        from deltalake import DeltaTable, write_deltalake

        table_uri = self._table_uri(table)
        
        # Cast any object columns that are completely null to string
        # to prevent `Invalid data type for Delta Lake: Null` error
        for col in data.columns:
            if data[col].dtype == 'object' and data[col].isnull().all():
                data[col] = data[col].astype(str)

        if not self._exists(table):
            write_deltalake(table_or_uri=table_uri, data=data, mode="overwrite")
            return

        dt = DeltaTable(table_uri)
        (
            dt.merge(
                source=data,
                predicate=f"s.{merge_key} = t.{merge_key}",
                source_alias="s",
                target_alias="t",
            )
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .execute()
        )

    # ------------------------------------------------------------------
    # Time-travel helpers
    # ------------------------------------------------------------------

    def get_versions(self, table: str) -> pd.DataFrame:
        """Return the full transaction history of a Delta table."""
        from deltalake import DeltaTable

        dt = DeltaTable(self._table_uri(table))
        return pd.DataFrame(dt.history())

    def read_version(self, table: str, version: int) -> pd.DataFrame:
        """Time-travel: read the Delta table at a specific historical version."""
        from deltalake import DeltaTable

        dt = DeltaTable(self._table_uri(table), version=version)
        return dt.to_pandas()
