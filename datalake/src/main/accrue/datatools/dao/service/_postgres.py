import os
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy import create_engine, text

from accrue.datatools.dao.service.interface import ServiceInterface


@dataclass
class PostgresService(ServiceInterface):
    host: str = field(default_factory=lambda: os.environ.get("PGHOST", "localhost"))
    port: int = field(default_factory=lambda: int(os.environ.get("PGPORT", "5432")))
    user: str = field(default_factory=lambda: os.environ.get("PGUSER", "postgres"))
    password: str = field(default_factory=lambda: os.environ.get("PGPASSWORD", "postgres"))
    database: str = field(default_factory=lambda: os.environ.get("PGDATABASE", "postgres"))

    @staticmethod
    def auto(**kwargs) -> "PostgresService":
        return PostgresService(**kwargs)

    @property
    def uri(self) -> str:
        """SQLAlchemy-compatible DSN URI."""
        return (
            f"postgresql+psycopg2://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
        )

    def engine(self):
        """Return a SQLAlchemy engine (connection pooled)."""
        return create_engine(self.uri)

    def connection(self):
        """Return a raw psycopg2 connection (useful for DDL / replication)."""
        import psycopg2
        return psycopg2.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            dbname=self.database,
        )

    def read_table(self, table: str, query: str | None = None) -> pd.DataFrame:
        """
        Read a full table (or a custom query) from Postgres into a Pandas DataFrame.
        """
        sql = query or f"SELECT * FROM {table}"
        with self.engine().connect() as conn:
            return pd.read_sql(text(sql), conn)

    def read_incremental(
        self,
        table: str,
        watermark_col: str,
        watermark_value: str,
        overlap_interval: str | None = None,
    ) -> pd.DataFrame:
        """
        Read only rows newer than watermark_value (minus overlap_interval if provided).
        Ideal for append-only tables that might arrive out-of-order.
        """
        if overlap_interval:
            # Assumes watermark is a timestamp if an interval is used
            sql = (
                f"SELECT * FROM {table} "
                f"WHERE {watermark_col} >= '{watermark_value}'::timestamp - INTERVAL '{overlap_interval}'"
            )
        else:
            sql = (
                f"SELECT * FROM {table} "
                f"WHERE {watermark_col} > '{watermark_value}'"
            )
        return self.read_table(table=table, query=sql)
