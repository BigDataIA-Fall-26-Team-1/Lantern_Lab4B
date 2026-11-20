"""Part 3 (Lab 35B): the LangGraph agent.

    START -> load_schema -> generate -> check --ok--> execute --ok--> summarize -> END
                               ^          |               |
                               +--repair--+-----repair----+     (at most max_attempts calls)

The nodes and routers come from askpanel.nodes.make_nodes; this file wires
them. The check node runs our Pydantic contract (validate_query) first, then
the kit's check. The checkpointer keeps each thread's history for follow-ups.

    app = build(model, tools, clock, P)
    s = app.invoke(nodes.new_state(q, prev), {"configurable": {"thread_id": "q01"}})
"""
import sys
from pathlib import Path
from typing import Optional, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from agent.contract import validate_query  # noqa: E402
from askpanel import nodes as kit  # noqa: E402


class AskState(TypedDict, total=False):
    """One key per askpanel.nodes.STATE_KEYS. No reducers: the kit's nodes
    return trace and history whole, so an add reducer would double them."""
    question: str
    history: list
    schema: str
    attempt: int
    query: Optional[dict]
    error: Optional[dict]
    result: Optional[dict]
    answer: Optional[str]
    trace: list
    usd: float
    tokens: int
    stop: Optional[str]
    run_id: str


def build(model, tools, clock, P, checkpointer=None):
    """The compiled graph. model: make_model(...) or a stand-in; tools: McpTools.as_node_tools()."""
    a = P["agent"]
    n, after_check, after_execute = kit.make_nodes(
        model, tools, clock, model_name=P["model"]["name"],
        max_attempts=int(a["max_attempts"]),
        usd_cap=float(a["usd_cap_per_question"]),
        token_cap=int(a["token_cap_per_question"]),
        allowed=set(P["server"]["tables"]))
    kit_check = n["check"]

    def check(state):
        """Our Pydantic contract first; a refused SQL goes back for repair."""
        _, err = validate_query(state["query"])
        if err and state["query"].get("sql") is not None:
            rec = {"run_id": state["run_id"], "step": len(state["trace"]) + 1,
                   "ts": clock().isoformat(), "node": "check", "outcome": err["code"]}
            return {"error": err, "attempt": state["attempt"] + 1,
                    "trace": state["trace"] + [rec]}
        return kit_check(state)                  # a decline, neither field, or ok

    g = StateGraph(AskState)
    g.add_node("load_schema", n["load_schema"])
    g.add_node("generate", n["generate"])
    g.add_node("check", check)
    g.add_node("execute", n["execute"])
    g.add_node("summarize", n["summarize"])

    g.add_edge(START, "load_schema")
    g.add_edge("load_schema", "generate")
    g.add_edge("generate", "check")
    g.add_conditional_edges("check", after_check,
                            {"execute": "execute", "generate": "generate",
                             "summarize": "summarize"})
    g.add_conditional_edges("execute", after_execute,
                            {"generate": "generate", "summarize": "summarize"})
    g.add_edge("summarize", END)
    return g.compile(checkpointer=checkpointer or InMemorySaver())