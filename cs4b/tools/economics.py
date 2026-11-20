"""Part 6 (Lab 36B): the numbers behind outputs/economics.md, from the saved outputs.

    python tools/economics.py

Reads outputs/questions/<id>.json (cost, model calls, outcome), outputs/latency.json
(question-to-answer seconds, from the record run) and params.yaml (prices and the
analyst assumptions). Re-runs each saved SQL through the MCP server (read-only) to
time the SQL itself and to confirm it still returns the saved rows.
Prints every number and writes outputs/economics_numbers.json. No API key needed.
"""
import json
import statistics
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from agent.mcp_client import McpTools  # noqa: E402
from agent.model import MIN_GAP_S  # noqa: E402
from askpanel import econ, questions  # noqa: E402
from services.mcp import server  # noqa: E402

P = yaml.safe_load((ROOT / "params.yaml").read_text(encoding="utf-8"))
qs = questions.load(ROOT / "questions/questions.yaml")
outs = [json.loads((ROOT / "outputs/questions" / f"{q['id']}.json").read_text(encoding="utf-8"))
        for q in qs]
lat_file = ROOT / "outputs/latency.json"
latency = json.loads(lat_file.read_text(encoding="utf-8")) if lat_file.exists() else {}


def outcome(o):
    """answered (SQL and rows), declined (no SQL, a reason), or failed."""
    if o.get("sql") is None:
        return "declined" if o.get("decline") else "failed"
    return "answered" if isinstance(o.get("result"), dict) else "failed"


# ------------------------------------------------ re-run each saved SQL through the server
sql_ms, same_rows = {}, {}
with McpTools(server.mcp) as mt:
    for o in outs:
        if outcome(o) != "answered":
            continue
        runs = [mt.call("run_query", sql=o["sql"]) for _ in range(3)]    # 3 runs, take the median
        sql_ms[o["id"]] = round(statistics.median(r["ms"] for r in runs), 1)
        same_rows[o["id"]] = runs[0]["rows"] == o["result"]["rows"]

# ------------------------------------------------ per question
print(f"{'id':4} {'category':12} {'outcome':9} {'calls':>5} {'usd':>10} {'tokens':>7} "
      f"{'latency_s':>9} {'sql_ms':>7}  same rows")
for o in outs:
    i = o["id"]
    print(f"{i:4} {o['category']:12} {outcome(o):9} {o['model_calls']:>5} {o['usd']:>10.6f} "
          f"{o['tokens']:>7} {latency.get(i, ''):>9} {sql_ms.get(i, ''):>7}  "
          f"{same_rows.get(i, '-')}")

# ------------------------------------------------ 1. cost
s = econ.summary(outs)
n = len(outs)
answered = [o for o in outs if outcome(o) == "answered"]
declined = [o for o in outs if outcome(o) == "declined"]
failed = [o for o in outs if outcome(o) == "failed"]
repaired = [o["id"] for o in answered if o["model_calls"] > 1]
total_usd = sum(o["usd"] for o in outs)
calls = sum(o["model_calls"] for o in outs)
tokens = sum(o["tokens"] for o in outs)

print("\n1. COST  (prices from params.yaml: "
      f"${P['prices']['usd_per_mtok_in']}/M in, ${P['prices']['usd_per_mtok_out']}/M out)")
print(f"   total for {n} questions: ${total_usd:.6f}  ({calls} model calls, {tokens:,} tokens)")
print(f"   per question asked:     ${total_usd / n:.6f}")
print(f"   per answered question:  ${total_usd / len(answered):.6f}  "
      f"(all {n} questions' cost, incl. repairs and the decline, over {len(answered)} answered)")
print(f"   model calls per question: {s['model_calls_per_question']}")

# ------------------------------------------------ 2. latency
lv = [latency[o["id"]] for o in outs if o["id"] in latency]
mv = list(sql_ms.values())
print("\n2. LATENCY")
if lv:
    print(f"   question to answer (record mode): median {statistics.median(lv):.2f} s, "
          f"mean {statistics.mean(lv):.2f} s, min {min(lv):.2f} s, max {max(lv):.2f} s")
    print(f"   note: includes the {MIN_GAP_S} s pause between Gemini calls (free-tier rate limit) "
          "and, for repaired questions, each failed attempt")
print(f"   SQL alone (median of 3 runs through the server): median {statistics.median(mv):.1f} ms, "
      f"max {max(mv):.1f} ms")

# ------------------------------------------------ 3. human time saved
mins = P["economics"]["analyst_minutes_per_question"]
rate = P["economics"]["analyst_rate_usd"]
human_per_q = mins / 60 * rate
print(f"\n3. HUMAN TIME SAVED  (assumption: {mins} min per ad-hoc question at ${rate:.0f}/hour)")
for row in econ.hours_saved_table(mins / 60, rate, tasks=len(answered)):
    print(f"   {row['scenario']:5} {row['hours']:.2f} hours = ${row['usd']:,.2f} "
          f"for {len(answered)} answered questions")
print(f"   analyst cost per question ${human_per_q:.2f} vs model cost ${total_usd / n:.6f}")

# ------------------------------------------------ 4. quality (what the traces can tell)
print("\n4. QUALITY  (from the traces; whether an answer is RIGHT is your own check)")
print(f"   answered {len(answered)}, of which repaired {len(repaired)} {repaired}; "
      f"declined {len(declined)}; failed {len(failed)}")
print(f"   saved rows reproduced through the server: "
      f"{sum(same_rows.values())}/{len(same_rows)}")

# ------------------------------------------------ saved, so economics.md can point at it
numbers = {
    "questions": n, "answered": len(answered), "declined": len(declined),
    "failed": len(failed), "repaired": repaired, "model_calls": calls, "tokens": tokens,
    "usd_total": round(total_usd, 6), "usd_per_question": round(total_usd / n, 6),
    "usd_per_answered": round(total_usd / len(answered), 6),
    "latency_s": {"median": statistics.median(lv), "max": max(lv)} if lv else None,
    "sql_ms": {"median": statistics.median(mv), "max": max(mv), "per_question": sql_ms},
    "same_rows": same_rows,
    "human": {"minutes_per_question": mins, "rate_usd": rate,
              "table": econ.hours_saved_table(mins / 60, rate, tasks=len(answered))},
}
(ROOT / "outputs/economics_numbers.json").write_text(
    json.dumps(numbers, indent=2) + "\n", encoding="utf-8", newline="\n")
print("\nwrote outputs/economics_numbers.json")