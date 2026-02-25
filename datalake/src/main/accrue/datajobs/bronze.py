from accrue.configs.contracts.catalog import ContractBronzeCatalog as ContractCatalog


for ref in ContractCatalog:
    contract = ref.load()
    print(f"Processing contract: {contract.table_name}")
    replicator = contract.to_replicator()
    if contract.refresh_mode == "full_reload":
        replicator.replicate_full()
    else:
        replicator.replicate_incremental(
            watermark_col=contract.watermark.column,
            fail_if_not_exists=False,
        )
print("Bronze layer complete.")
