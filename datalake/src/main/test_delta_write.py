from accrue.configs.contracts.catalog import ContractCatalog
import pandas as pd

contract = ContractCatalog.CHECKOUT_PAYMENTS.load()
replicator = contract.to_replicator()
df = replicator.read_full()
print(df.info())
print(df.dtypes)
print(df.head())
