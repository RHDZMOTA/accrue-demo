from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Column / Watermark specs
# ---------------------------------------------------------------------------

@dataclass
class ColumnSpec:
    name: str
    type: str  # TEXT, NUMERIC, TIMESTAMP, INTEGER, ...

    @classmethod
    def from_dict(cls, data: dict) -> "ColumnSpec":
        return cls(name=data["name"], type=data["type"])


@dataclass
class WatermarkSpec:
    column: str
    type: str  # TIMESTAMP | INTEGER
    overlap_interval: str = "1 day"

    @classmethod
    def from_dict(cls, data: dict) -> "WatermarkSpec":
        return cls(
            column=data["column"],
            type=data["type"],
            overlap_interval=data.get("overlap_interval", "1 day"),
        )


# ---------------------------------------------------------------------------
# Quality rules
# ---------------------------------------------------------------------------

@dataclass
class QualityRule:
    """
    A single data quality assertion expected from the source system.

    rule_type options:
      - not_null       : columns must have no nulls  → requires: columns
      - unique         : columns (combo) must be unique → requires: columns
      - value_range    : numeric/datetime bounds       → requires: column + min/max
      - allowed_values : enum check                   → requires: column + values
      - regex          : pattern match                 → requires: column + pattern
      - row_count_min  : table must have >= N rows    → requires: count
    """
    rule_type: str
    columns: list[str] = field(default_factory=list)
    column: str | None = None
    min: float | None = None
    max: float | None = None
    values: list[str] = field(default_factory=list)
    pattern: str | None = None
    count: int | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "QualityRule":
        return cls(
            rule_type=data["rule_type"],
            columns=data.get("columns", []),
            column=data.get("column"),
            min=data.get("min"),
            max=data.get("max"),
            values=data.get("values", []),
            pattern=data.get("pattern"),
            count=data.get("count"),
        )


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------

@dataclass
class Contract:
    # Identity
    contract_version: str
    description: str
    owner: str
    tags: list[str]

    # Source
    source_service_type: str    # matches ServiceCatalog enum name: POSTGRES, DELTA, ...
    database_schema: str        # e.g. "public"
    table_name: str

    # Target
    target_service_type: str    # matches ServiceCatalog enum name: DELTA, ...
    target_layer: str           # bronze | silver | gold
    target_tablename: str

    # Replication strategy
    refresh_mode: str           # incremental | full_reload

    # Schema (non-negotiables only)
    primary_keys: list[ColumnSpec]
    watermark: WatermarkSpec | None

    # Quality
    quality_rules: list[QualityRule]

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict) -> "Contract":
        return cls(
            contract_version=data["contract_version"],
            description=data.get("description", ""),
            owner=data.get("owner", ""),
            tags=data.get("tags", []),
            source_service_type=data["source_service_type"],
            database_schema=data.get("database_schema", "public"),
            table_name=data["table_name"],
            target_service_type=data["target_service_type"],
            target_layer=data["target_layer"],
            target_tablename=data["target_tablename"],
            refresh_mode=data["refresh_mode"],
            primary_keys=[ColumnSpec.from_dict(pk) for pk in data.get("primary_keys", [])],
            watermark=WatermarkSpec.from_dict(data["watermark"]) if data.get("watermark") else None,
            quality_rules=[QualityRule.from_dict(r) for r in data.get("quality_rules", [])],
        )

    @classmethod
    def from_json(cls, path: str) -> "Contract":
        with open(path, "r") as f:
            return cls.from_dict(json.load(f))

    # ------------------------------------------------------------------
    # Integration helpers
    # ------------------------------------------------------------------

    def source_service(self, **kwargs):
        """Instantiate the source service from the contract's source_service_type."""
        from accrue.datatools.dao.service.catalog import ServiceCatalog
        return ServiceCatalog[self.source_service_type](**kwargs)

    def target_service(self, **kwargs):
        """Instantiate the target service from the contract's target_service_type."""
        from accrue.datatools.dao.service.catalog import ServiceCatalog
        return ServiceCatalog[self.target_service_type](**kwargs)

    def to_replicator(self, source_kwargs: dict | None = None, target_kwargs: dict | None = None):
        """Build a Replicator pre-wired from this contract."""
        from accrue.datatools.replicator import Replicator
        return Replicator(
            source_tablename=self.table_name,
            source_service=self.source_service(**(source_kwargs or {})),
            target_tablename=self.target_tablename,
            target_service=self.target_service(**(target_kwargs or {})),
            contract=self,
        )
    
    def to_transformer(self, source_kwargs: dict | None = None, target_kwargs: dict | None = None):
        """Build a Transformer pre-wired from this contract."""
        from accrue.datatools.transformer.catalog import TransformerCatalog
        *_, key = self.table_name.upper().split("/")
        return TransformerCatalog[key](
            source_table=self.table_name,
            source_service=self.source_service(**(source_kwargs or {})),
            target_table=self.target_tablename,
            target_service=self.target_service(**(target_kwargs or {})),
        )
