"""Part 4 (Lab 36B): the Ask the Panel chat app.

    streamlit run app/streamlit_app.py      # replay by default: no API key needed

The app is thin: it calls the same graph as agent/run.py, and it reaches the
data only through McpTools and the MCP server, never the database directly.
"""
import os
import sys
import uuid
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

# ---------------------------------------------------------------- (A) paths
# The app lives in app/, but imports code from agent/, services/ and src/askpanel.
ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from agent.graph import build  # noqa: E402
from agent.mcp_client import McpTools  # noqa: E402
from agent.model import make_model  # noqa: E402
from askpanel import clock, llm, nodes  # noqa: E402
from services.mcp import server  # noqa: E402

P = yaml.safe_load((ROOT / "params.yaml").read_text(encoding="utf-8"))

st.set_page_config(page_title="Ask the Panel", page_icon="🏮", layout="wide")


# ---------------------------------------------------------------- (B) build once
# Streamlit re-runs this whole script on every click. cache_resource runs
# get_agent only the first time (per mode) and reuses the result after that,
# so we keep ONE MCP session and ONE graph (and its conversation memory).
@st.cache_resource(show_spinner="Starting the MCP session and the agent...")
def get_agent(mode):
    mt = McpTools(server.mcp)                                # one MCP session, kept open
    model = make_model(P, mode)                              # Gemini behind record/replay
    app = build(model, mt.as_node_tools(), clock.clock, P)   # the LangGraph agent
    return app, mt


# ---------------------------------------------------------------- (D) this tab's memory
# session_state belongs to ONE browser tab and survives re-runs:
# the conversation id (thread) and the messages shown on screen.
st.session_state.setdefault("thread", str(uuid.uuid4()))
st.session_state.setdefault("messages", [])


def new_conversation():
    """A new thread id = an empty history for the next question."""
    st.session_state.thread = str(uuid.uuid4())
    st.session_state.messages = []


# ---------------------------------------------------------------- (C) sidebar
# Replay is the default (from params.yaml); record only works with a key.
with st.sidebar:
    st.header("Settings")
    modes = ["replay", "record"]
    default = P["model"]["mode"] if P["model"]["mode"] in modes else "replay"
    mode = st.radio("Model mode", modes, index=modes.index(default),
                    help="replay: saved answers only, no key, no cost. record: calls Gemini.")
    if mode == "record" and not os.environ.get("GEMINI_API_KEY"):
        st.warning("Record mode needs `GEMINI_API_KEY`, so the app is using replay.")
        mode = "replay"
    st.caption(f"Model: {P['model']['name']}")

    st.divider()
    st.button("New conversation", on_click=new_conversation, type="primary",
              use_container_width=True)
    st.caption(f"Conversation `{st.session_state.thread[:8]}` · "
               f"{len(st.session_state.messages) // 2} question(s) so far")

app, _mt = get_agent(mode)

st.title("Ask the Panel")
st.caption("Ask a question about the BDC holdings. Every answer comes with the SQL behind it.")

REPLAY_HINT = (
    "This question is not in the replay cache. In replay mode, ask a recorded question "
    "word for word as the FIRST question of a new conversation, or a follow-up right "
    "after the question it follows. For anything else, switch to record mode "
    "(needs `GEMINI_API_KEY`).")


# ---------------------------------------------------------------- (E) ask one question
# Same as agent/run.py: same thread id -> the graph's saved history -> invoke.
def ask(question):
    cfg = {"configurable": {"thread_id": st.session_state.thread}}
    prev = app.get_state(cfg).values.get("history", [])      # earlier questions + their SQL
    run_id = f"app-{len(st.session_state.messages) // 2 + 1}"
    try:
        s = app.invoke(nodes.new_state(question, prev, run_id=run_id), cfg)
    except llm.CacheMiss:                                    # replay has no saved answer
        return {"role": "assistant", "error": REPLAY_HINT}
    except Exception as e:  # noqa: BLE001                   # e.g. a Gemini error in record mode
        return {"role": "assistant", "error": f"{type(e).__name__}: {e}"}
    query = s.get("query") or {}
    return {"role": "assistant", "answer": s.get("answer"), "sql": query.get("sql"),
            "decline": query.get("decline"), "result": s.get("result"),
            "usd": s.get("usd", 0.0), "tokens": s.get("tokens", 0), "stop": s.get("stop"),
            "model_calls": sum(t["node"] == "generate" for t in s.get("trace", [])),
            "trace": s.get("trace", [])}


# ---------------------------------------------------------------- (F) draw one reply
def rows_table(result):
    """The result rows as a DataFrame (duplicate column names made unique)."""
    cols, seen = [], {}
    for c in result["columns"]:
        seen[c] = seen.get(c, 0) + 1
        cols.append(c if seen[c] == 1 else f"{c}_{seen[c]}")
    return pd.DataFrame(result["rows"], columns=cols)


TRACE_FIRST = ["step", "node", "outcome", "attempt"]          # the columns that tell the story


def _cell(key, v):
    """One trace value as text: whole numbers stay whole, keys are shortened."""
    if v is None:
        return ""
    if key == "request_key":
        return v[:12]
    if isinstance(v, float):
        return f"{v:.6f}"
    return str(v)


def trace_table(trace):
    """One row per graph step, the important columns first."""
    rows = [{k: _cell(k, v) for k, v in t.items() if k not in ("run_id", "ts")}
            for t in trace]
    df = pd.DataFrame(rows).fillna("")
    first = [c for c in TRACE_FIRST if c in df]
    return df[first + [c for c in df.columns if c not in first]]


def show_reply(m):
    if m.get("error"):                                       # CacheMiss or another error
        st.warning(m["error"])
        return

    r = m.get("result")
    # 1. the answer
    if r is not None:                                        # rows came back
        st.markdown(f"**{m['answer'].splitlines()[0]}**")    # e.g. "5 row(s)"
    elif m.get("decline"):                                   # the agent declined
        st.info(f"Declined: {m['answer']}")
    else:                                                    # out of attempts or over budget
        st.error(m["answer"])

    # 2. the SQL behind it (wrapped, so the whole query is on screen)
    if m.get("sql"):
        st.code(m["sql"], language="sql", wrap_lines=True)

    # 3. the rows, as a table
    if r is not None:
        st.dataframe(rows_table(r), hide_index=True, use_container_width=True)
        if r.get("truncated"):
            st.caption(f"Showing the first {r['row_count']} rows (the server's row cap).")

    # 4. cost and model calls (more than one call means the repair edge ran)
    repaired = " (repaired)" if m["model_calls"] > 1 and r is not None else ""
    st.caption(f"Cost ${m['usd']:.5f} · {m['model_calls']} model call(s){repaired} · "
               f"{m['tokens']:,} tokens")

    # 5. the trace: every step the graph took, e.g. execute[invalid] -> generate again
    with st.expander("Trace"):
        st.dataframe(trace_table(m["trace"]), hide_index=True, use_container_width=True)


# ---------------------------------------------------------------- (G) the chat
# Redraw the whole conversation, then wait for the next question.
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        if m["role"] == "user":
            st.write(m["text"])
        else:
            show_reply(m)

# Curly quotes (from Word, PDFs, websites) look the same as straight ones but are
# different characters, so they would change the replay fingerprint. Straighten them.
STRAIGHT = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'})

if q := st.chat_input("Ask about the BDC holdings"):
    q = q.translate(STRAIGHT).strip()
    st.session_state.messages.append({"role": "user", "text": q})
    with st.spinner("Thinking (a repaired question can take ~10 s)..."):
        st.session_state.messages.append(ask(q))
    st.rerun()