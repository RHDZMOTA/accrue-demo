from deltalake import DeltaTable


def append_to_delta(
    table: DeltaTable | str,
    data: pd.DataFrame,
    mode: str = "append",
    partition_by: list[str] | None = None,
):
    from deltalake import write_deltatable

    if isinstance(table, str):
        table = DeltaTable(table)
    
    write_deltatable(
        table=table,
        data=data,
        mode=mode,
        partition_by=partition_by,
    )
