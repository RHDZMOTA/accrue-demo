from accrue.configs.contracts.catalog import ContractSilverCatalog


for ref in ContractSilverCatalog:
    contract = ref.load()
    print(f"  Processing: {ref.value}")
    transformer = contract.to_transformer()
    transformer.run()

print("Silver layer complete.")
