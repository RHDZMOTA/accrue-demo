import pandas as pd


class ServiceInterface:

    @staticmethod
    def auto(**kwargs) -> "ServiceInterface":
        raise NotImplementedError

    def read_table(self, table: str, query: str | None = None) -> pd.DataFrame:
        raise NotImplementedError

    def read_incremental(
        self,
        table: str,
        watermark_col: str,
        watermark_value: str,
        overlap_interval: str | None = None,
    ) -> pd.DataFrame:
        raise NotImplementedError
