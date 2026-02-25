import os
from deltalake import write_deltalake
import pandas as pd

# Let's try to bypass the absolute path entirely by setting our current working directory
# and using a purely relative path without the bracketed folder.

# The Python virtual env is running inside:
# /Users/rhdzmota/Documents/[4R7.FHR] 4R7e/Accrue/payments-fraud-data-exercise/

print("Trying pure relative path (no file:, no leading slash)...")
target_path = "./datalake/layer/test_table3"

try:
    write_deltalake(target_path, pd.DataFrame({"id": [3]}), mode="overwrite")
    print("SUCCESS")
except Exception as e:
    print(f"FAILED: {e}")
