"""Clean the real Lab 3B panel's blank fair values.

In the filings, a blank fair value is a dash, meaning $0. Two cases:
  - cost > 0: a written-off holding (money went out, now worth $0).
    Kept, with fair_value set to 0, so its price is 0.
  - no cost: an unfunded commitment (promised, not yet lent).
    Dropped: its "principal" is only a promise, and a price of 0
    would make a new loan look like a default.

Reads data/real/panel_2p_raw.parquet, writes data/real/panel_2p.parquet,
which build_db.py uses.

    python tools/clean_panel.py
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/real/panel_2p_raw.parquet"
OUT = ROOT / "data/real/panel_2p.parquet"

p = pd.read_parquet(RAW)
p["fair_value"] = pd.to_numeric(p["fair_value"], errors="coerce")
cost = pd.to_numeric(p["cost"], errors="coerce")

blank = p["fair_value"].isna()
written_off = blank & (cost > 0)
principal = pd.to_numeric(p["principal"], errors="coerce")
unfunded = blank & ~(cost > 0) & (principal > 0)

print(f"{len(p)} rows in; {int(blank.sum())} with a blank fair value")
for label, mask in [("written off -> fair_value 0 (kept)", written_off),
                    ("unfunded commitment (dropped)", unfunded)]:
    print(f"\n{label}: {int(mask.sum())}")
    print(p[mask].groupby(["period_role", "name"]).size().to_string())

p.loc[written_off, "fair_value"] = 0.0
out = p[~unfunded]
out.to_parquet(OUT, index=False)
print(f"\n{len(out)} rows written to {OUT.relative_to(ROOT)} "
      f"({int((out['period_role'] == 'current').sum())} current)")