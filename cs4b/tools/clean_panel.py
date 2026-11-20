"""Clean the real Lab 3B panel's unfunded and written-off holdings.

In the filings, a blank fair value is a dash, meaning $0. Three cases:
  - blank fair value, cost > 0: a written-off holding (money went out, now
    worth $0). Kept, with fair_value set to 0, so its price is 0.
  - blank fair value, no cost: an unfunded commitment (promised, not yet lent).
    Dropped: its "principal" is only a promise, and a price of 0 would make a
    new loan look like a default.
  - fair value <= 0, no positive cost, principal > 0: an unfunded commitment the
    filing marks at $0 or a small negative value (the discount on the unfunded
    part). Dropped for the same reason: its "price" is meaningless (about -1.5)
    and drags a BDC's average price down. Found in Lab 4B (q06, WEST BAY BDC).

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
principal = pd.to_numeric(p["principal"], errors="coerce")

blank = p["fair_value"].isna()
written_off = blank & (cost > 0)
unfunded = blank & ~(cost > 0) & (principal > 0)
unfunded_marked = ~blank & (p["fair_value"] <= 0) & ~(cost > 0) & (principal > 0)

print(f"{len(p)} rows in; {int(blank.sum())} with a blank fair value")
for label, mask in [("written off -> fair_value 0 (kept)", written_off),
                    ("unfunded commitment, blank (dropped)", unfunded),
                    ("unfunded commitment, marked <= 0 (dropped)", unfunded_marked)]:
    print(f"\n{label}: {int(mask.sum())}")
    if mask.any():
        print(p[mask].groupby(["period_role", "name"]).size().to_string())

p.loc[written_off, "fair_value"] = 0.0
out = p[~(unfunded | unfunded_marked)]
out.to_parquet(OUT, index=False)
print(f"\n{len(out)} rows written to {OUT.relative_to(ROOT)} "
      f"({int((out['period_role'] == 'current').sum())} current)")
