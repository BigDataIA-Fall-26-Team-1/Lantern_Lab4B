"""Part 3 (Lab 35B): answer questions/questions.yaml and save each answer.

    python agent/run.py --mode record     # calls Gemini (needs GEMINI_API_KEY), fills outputs/cache/
    python agent/run.py --mode replay     # cache only: free, offline, identical traces

Writes outputs/questions/<id>.json. A follow_up question continues the thread
of the question it follows, so its history holds that question and its SQL.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from agent.graph import build  # noqa: E402
from agent.mcp_client import McpTools  # noqa: E402
from agent.model import make_model  # noqa: E402
from askpanel import clock, econ, llm, nodes, questions  # noqa: E402
from services.mcp import server  # noqa: E402


def output(q, s):
    """The saved record for one question (the self-check's OUTPUT_FIELDS, plus a few extras)."""
    query = s.get("query") or {}
    result = s.get("result")
    if result is not None:
        result = {k: v for k, v in result.items() if k != "ms"}   # wall-clock time: kept out so replays match
    return {"id": q["id"], "question": q["question"], "category": q["category"],
            "follows": q.get("follows"),
            "sql": query.get("sql"), "decline": query.get("decline"),
            "explanation": query.get("explanation", ""),
            "answer": s.get("answer"), "result": result, "trace": s.get("trace", []),
            "usd": round(s.get("usd", 0.0), 8), "tokens": s.get("tokens", 0),
            "model_calls": sum(t["node"] == "generate" for t in s.get("trace", [])),
            "stop": s.get("stop")}


def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n",
                    encoding="utf-8", newline="\n")


def main():
    P = yaml.safe_load((ROOT / "params.yaml").read_text())
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mode", choices=["record", "replay"], default=P["model"]["mode"])
    ap.add_argument("--questions", default="questions/questions.yaml")
    ap.add_argument("--out", default="outputs/questions")
    ap.add_argument("--cache", default=None, help="cache folder (default: model.cache_dir)")
    ap.add_argument("--only", nargs="*", help="run only these ids (plus the questions they follow)")
    args = ap.parse_args()

    if args.mode == "record" and not os.environ.get("GEMINI_API_KEY"):
        sys.exit("record mode needs GEMINI_API_KEY (PowerShell: $env:GEMINI_API_KEY = \"...\")")
    if os.environ.get("LANTERN_CLOCK") == "live":
        print("warning: LANTERN_CLOCK=live makes traces differ between runs")

    qs = questions.load(ROOT / args.questions)
    probs = questions.validate(qs)
    if probs and args.questions.endswith("questions.yaml"):
        print("note:", "; ".join(probs))
    keep = set(args.only or [q["id"] for q in qs])
    for q in qs:                                   # a follow-up needs its parent in the run
        if q["id"] in keep and q.get("follows"):
            keep.add(q["follows"])

    out_dir = ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    model = make_model(P, args.mode, cache_dir=ROOT / args.cache if args.cache else None)

    threads, saved, failed, latency = {}, [], [], {}
    with McpTools(server.mcp) as mt:
        app = build(model, mt.as_node_tools(), clock.clock, P)
        for q in qs:
            if q["id"] not in keep:
                continue
            tid = threads.get(q.get("follows"), q["id"]) if q.get("follows") else q["id"]
            threads[q["id"]] = tid
            cfg = {"configurable": {"thread_id": tid}}
            prev = app.get_state(cfg).values.get("history", [])
            t0 = time.perf_counter()
            try:
                s = app.invoke(nodes.new_state(q["question"], prev, run_id=q["id"]), cfg)
            except llm.CacheMiss as e:
                failed.append(q["id"])
                print(f"  MISS  {q['id']}: not in the replay cache ({e}); record it again")
                continue
            except Exception as e:  # noqa: BLE001  (e.g. an API error in record mode)
                failed.append(q["id"])
                print(f"  FAIL  {q['id']}: {type(e).__name__}: {str(e)[:200]}")
                continue
            latency[q["id"]] = round(time.perf_counter() - t0, 2)
            o = output(q, s)
            write_json(out_dir / f"{q['id']}.json", o)
            saved.append(o)
            path = " -> ".join(t["node"] + (f"[{t['outcome']}]" if t.get("outcome") else "")
                               for t in o["trace"] if t["node"] != "load_schema")
            rows = o["result"]["row_count"] if o["result"] else "-"
            print(f"  OK    {q['id']} ({q['category']}, thread {tid}): rows {rows}, "
                  f"{o['model_calls']} call(s), ${o['usd']:.5f}\n        {path}")

    if args.mode == "record" and latency:          # question-to-answer seconds, for Part 6
        write_json(out_dir.parent / "latency.json", latency)
    print(f"\n{len(saved)} saved, {len(failed)} failed ({args.mode} mode)")
    if saved:
        print("summary:", econ.summary(saved))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())