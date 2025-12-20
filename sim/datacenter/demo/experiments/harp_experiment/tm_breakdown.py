import pandas as pd
import numpy as np
import os

csv_path = '../../../../../all_tms.csv'
if not os.path.isfile(csv_path):
    raise FileNotFoundError(f"CSV not found: {csv_path}")

df = pd.read_csv(csv_path)

print(df.head())  # Display the first few rows to understand the structure

# Ensure tm_id exists
if 'tm_id' not in df.columns:
    raise KeyError("Column 'tm_id' not found in dataframe")

# Output directory next to the input CSV
out_dir = os.path.join(os.path.dirname(csv_path), 'harp_csvs')
os.makedirs(out_dir, exist_ok=True)

# Split and write one CSV per tm_id (handle NaN values)
for tm_id, group in df.groupby('tm_id', dropna=False):
    safe_id = 'nan' if pd.isna(tm_id) else str(tm_id)
    safe_id = "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in safe_id)
    out_file = os.path.join(out_dir, f"tm_{safe_id}.csv")
    group.to_csv(out_file, index=False)
    print(f"Saved {len(group)} rows -> {out_file}")
