"""Smoke test for agent/graph.py: stand-in model, real MCP server, no API key.
    python tools/smoke_graph.py"""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from agent.graph import build  # noqa: E402
from agent.mcp_client import McpTools  # noqa: E402
from askpanel import clock, nodes, standin  # noqa: E402
from services.mcp import server  # noqa: E402

P = yaml.safe_load((ROOT / "params.yaml").read_text())
with McpTools(server.mcp) as mt:
    app = build(standin.FixtureSQLModel(), mt.as_node_tools(), clock.clock, P)
    cfg = {"configurable": {"thread_id": "smoke"}}
    for i, q in enumerate(["How many current holdings does each BDC report?",
                           "Which current debt holdings carry a PIK rate above 2%?",
                           "What will next quarter's NAV be?"], 1):
        prev = app.get_state(cfg).values.get("history", [])
        s = app.invoke(nodes.new_state(q, prev, run_id=f"smoke-{i}"), cfg)
        path = " -> ".join(t["node"] + (f"[{t['outcome']}]" if t.get("outcome") else "")
                           for t in s["trace"])
        print(f"\n{q}\n  {path}\n  {s['answer'].splitlines()[0]}")
    print("\nhistory turns kept by the checkpointer:", len(app.get_state(cfg).values["history"]))