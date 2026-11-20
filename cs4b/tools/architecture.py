"""The README's architecture diagram: python tools/architecture.py -> docs/architecture.png

Drawing only: needs Graphviz (`dot`) and `pip install diagrams`. Neither is needed to
run, test or grade the lab, so they are not in requirements.txt.
"""
from pathlib import Path

from diagrams import Cluster, Diagram, Edge
from diagrams.gcp.ml import AIPlatform
from diagrams.generic.database import SQL
from diagrams.generic.storage import Storage
from diagrams.onprem.client import User
from diagrams.programming.language import Python

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "architecture"          # diagrams adds the .png
OUT.parent.mkdir(exist_ok=True)


def box(fill, line):
    """A coloured, rounded cluster, like the panels in a slide."""
    return {"bgcolor": fill, "pencolor": line, "penwidth": "2", "style": "rounded",
            "fontsize": "15", "fontname": "Helvetica-Bold", "margin": "20"}


GRAPH = {"fontsize": "22", "fontname": "Helvetica-Bold", "pad": "0.6",
         "nodesep": "0.8", "ranksep": "1.1", "splines": "spline",
         "labelloc": "t"}                     # title at the top
NODE = {"fontsize": "12", "fontname": "Helvetica"}

# edge styles: one colour per kind of arrow
FLOW = {"color": "#495057", "penwidth": "2", "fontsize": "11"}
OK = {"color": "#2B8A3E", "penwidth": "2", "fontsize": "11"}
DECLINE = {"color": "#7048E8", "penwidth": "2", "fontsize": "11"}
REPAIR = {"color": "#E03131", "penwidth": "2", "fontsize": "11", "style": "dashed",
          "constraint": "false"}              # drawn backwards without changing the layout
RETURN = {"color": "#495057", "penwidth": "2", "fontsize": "11",
          "constraint": "false"}              # the answer goes back without moving the app
MODEL = {"color": "#F08C00", "penwidth": "2", "fontsize": "11"}
MCP = {"color": "#0CA678", "penwidth": "2", "fontsize": "11"}

with Diagram("Ask the Panel: one read-only path to the data", filename=str(OUT),
             outformat="png", show=False, direction="LR",
             graph_attr=GRAPH, node_attr=NODE):

    analyst = User("Analyst")

    with Cluster("INTERFACE  (app/)", graph_attr=box("#FDE2E4", "#D6336C")):
        app = Python("streamlit_app.py\n(Streamlit chat)")

    with Cluster("LANGGRAPH AGENT  (agent/graph.py)", graph_attr=box("#E7F1FF", "#1971C2")):
        with Cluster("five nodes  (askpanel.nodes)", graph_attr=box("#F5F9FF", "#74A9E8")):
            load = Python("load_schema")
            gen = Python("generate")
            chk = Python("check\n(Pydantic SQLQuery,\nagent/contract.py)")
            exe = Python("execute")
            summ = Python("summarize")
        client = Python("mcp_client.py\n(McpTools, sync)")

    with Cluster("MODEL  (agent/model.py)", graph_attr=box("#FFF4D6", "#F08C00")):
        replay = Python("ReplayClient\n(record / replay)")
        cache = Storage("outputs/cache/\n(recorded replies)")
        gemini = AIPlatform("Gemini\ngemini-3.5-flash-lite\n(record mode only)")

    with Cluster("MCP SERVER  (services/mcp/server.py)", graph_attr=box("#E6FCF5", "#0CA678")):
        tools = Python("4 READ tools\nlist_tables, describe_table\nsample_values, run_query")
        gate = Python("SQL gate (askpanel.gate)\none SELECT, row cap,\ntimeout")
        ledger = Storage("audit ledger\n(every call and refusal)")

    with Cluster("DATA", graph_attr=box("#F1F3F5", "#495057")):
        db = SQL("SQLite, read-only\nmode=ro + authorizer\nfilings, holdings,\nholdings_v")

    # the question's path through the graph
    analyst >> Edge(label="question", **FLOW) >> app
    app >> Edge(label="question +\nthread history", **FLOW) >> load
    load >> Edge(**FLOW) >> gen
    gen >> Edge(**FLOW) >> chk
    chk >> Edge(label="ok", **OK) >> exe
    exe >> Edge(label="ok", **OK) >> summ
    chk >> Edge(label="decline", **DECLINE) >> summ
    chk >> Edge(label="repair: Pydantic refused\n(max 3 model calls)", **REPAIR) >> gen
    exe >> Edge(label="repair: SQL failed\n(max 3 model calls)", **REPAIR) >> gen
    summ >> Edge(label="answer, SQL,\nrows, cost", **RETURN) >> app

    # the model, behind record/replay
    gen >> Edge(label="request", **MODEL) >> replay
    replay >> Edge(label="replay", **MODEL) >> cache
    replay >> Edge(label="record", style="dashed", **MODEL) >> gemini

    # the only path to the data
    load >> Edge(label="list / describe", **MCP) >> client
    exe >> Edge(label="run_query", **MCP) >> client
    client >> Edge(label="MCP", **MCP) >> tools
    tools >> Edge(**MCP) >> gate
    tools >> Edge(style="dotted", **MCP) >> ledger
    gate >> Edge(label="SELECT only", **MCP) >> db

print(f"wrote {OUT.with_suffix('.png').relative_to(ROOT)}")