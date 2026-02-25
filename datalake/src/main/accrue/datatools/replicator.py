from dataclasses import dataclass

import uuid

import pandas as pd

from accrue.configs.contracts.interface import Contract
from accrue.datatools.dao.service.interface import ServiceInterface


@dataclass
class Replicator:
    """
    Replicates a table from a source service to a target service.
    Typical usage: Postgres (source) → Delta Lake (target).
    """
    source_tablename: str
    source_service: ServiceInterface
    target_tablename: str
    target_service: ServiceInterface
    contract: Contract | None = None

    def __post_init__(self):
        if self.source_service is None:
            self.source_service = ServiceInterface.auto()
        if self.target_service is None:
            self.target_service = ServiceInterface.auto()

    def read_full(self) -> pd.DataFrame:
        """Full read of the source table."""
        return self.source_service.read_table(self.source_tablename)

    def read_incremental(self, watermark_col: str, watermark_value: str) -> pd.DataFrame:
        """Incremental read — only rows newer than watermark_value minus overlap."""
        overlap = self.contract.watermark.overlap_interval if (self.contract and self.contract.watermark) else None
        return self.source_service.read_incremental(
            table=self.source_tablename,
            watermark_col=watermark_col,
            watermark_value=watermark_value,
            overlap_interval=overlap,
        )

    def replicate_full(self) -> pd.DataFrame:
        """Full replication: read all from source, overwrite target."""
        df = self.read_full()
        self._validate_quality_constraint(df)
        self._add_metadata_uuids(df)
        self.target_service.write(
            table=self.target_tablename,
            data=df,
            mode="overwrite",
        )
        return df

    def _validate_quality_constraint(self, df: pd.DataFrame) -> None:
        """Validate the DataFrame against the Contract's QualityRules before writing."""
        if self.contract is None or not self.contract.quality_rules:
            return

        for rule in self.contract.quality_rules:
            if rule.rule_type == "not_null":
                for col in rule.columns:
                    if col in df.columns and df[col].isnull().any():
                        raise ValueError(f"Quality validation failed: Column '{col}' contains nulls.")
            elif rule.rule_type == "unique":
                if not df.empty and df.duplicated(subset=rule.columns).any():
                    raise ValueError(f"Quality validation failed: Columns {rule.columns} are not unique.")
            elif rule.rule_type == "value_range":
                if rule.column in df.columns:
                    if rule.min is not None and (df[rule.column] < rule.min).any():
                        raise ValueError(f"Quality validation failed: '{rule.column}' has values < {rule.min}.")
                    if rule.max is not None and (df[rule.column] > rule.max).any():
                        raise ValueError(f"Quality validation failed: '{rule.column}' has values > {rule.max}.")
            elif rule.rule_type == "allowed_values":
                if rule.column in df.columns:
                    invalid_mask = ~df[rule.column].isin(rule.values)
                    if invalid_mask.any():
                        invalid_values = df.loc[invalid_mask, rule.column].unique()
                        raise ValueError(f"Quality validation failed: '{rule.column}' contains disallowed values {invalid_values}.")
            elif rule.rule_type == "regex":
                if rule.column in df.columns and rule.pattern:
                    if not df[rule.column].astype(str).str.match(rule.pattern).all():
                        raise ValueError(f"Quality validation failed: '{rule.column}' does not match regex '{rule.pattern}'.")
            elif rule.rule_type == "row_count_min":
                if rule.count is not None and len(df) < rule.count:
                    raise ValueError(f"Quality validation failed: row count {len(df)} is less than required minimum {rule.count}.")

    def _add_metadata_uuids(self, df: pd.DataFrame) -> None:
        """Appends META_KEYS_UUID and META_DATA_UUID to the dataframe."""
        if df.empty:
            return

        # Identify primary keys (fallback to 'id' if contract is missing)
        pk_cols = [pk.name for pk in self.contract.primary_keys] if self.contract and self.contract.primary_keys else ["id"]
        valid_pk_cols = [c for c in pk_cols if c in df.columns]

        if not valid_pk_cols:
            raise ValueError(f"Cannot generate UUIDs: Primary keys {pk_cols} not found in dataframe.")

        # Hash the primary keys subset
        keys_hash = pd.util.hash_pandas_object(df[valid_pk_cols], index=False).astype(str)
        df["META_KEYS_UUID"] = keys_hash.apply(lambda x: str(uuid.uuid5(uuid.NAMESPACE_OID, x)))

        # Hash the entire row payload (excluding the metadata ones if they already exist)
        payload_cols = [c for c in df.columns if c not in ("META_KEYS_UUID", "META_DATA_UUID")]
        data_hash = pd.util.hash_pandas_object(df[payload_cols], index=False).astype(str)
        df["META_DATA_UUID"] = data_hash.apply(lambda x: str(uuid.uuid5(uuid.NAMESPACE_OID, x)))

    def _resolve_watermark(self, watermark_col: str) -> str | None:
        """
        Return MAX(watermark_col) from the target table, or None if the target
        doesn't exist / is empty (signals a first-run full replication).
        """
        try:
            df = self.target_service.read_table(self.target_tablename)
            if df.empty:
                return None
            return str(df[watermark_col].max())
        except Exception:
            return None

    def replicate_incremental(
        self,
        watermark_col: str,
        watermark_value: str | None = None,
        merge_key: str = "id",
        fail_if_not_exists: bool = False,
    ) -> pd.DataFrame:
        """
        Incremental replication: read new rows from source, upsert into target.
        Idempotent — re-running with the same watermark is safe.

        If watermark_value is None, it is auto-resolved from MAX(watermark_col)
        on the target table. On first run (empty/missing target), falls back to
        replicate_full() so the pipeline bootstraps itself automatically, unless
        fail_if_not_exists is True.
        """
        resolved = watermark_value or self._resolve_watermark(watermark_col)
        if resolved is None:
            if fail_if_not_exists:
                raise ValueError(f"Target table '{self.target_tablename}' does not exist or is empty.")
            # Target is empty or missing — bootstrap with a full replication
            return self.replicate_full()
        df = self.read_incremental(
            watermark_col=watermark_col,
            watermark_value=resolved,
        )
        if df.empty:
            return df
        self._validate_quality_constraint(df)
        self._add_metadata_uuids(df)
        self.target_service.upsert(
            table=self.target_tablename,
            data=df,
            merge_key=merge_key,
        )
        return df
