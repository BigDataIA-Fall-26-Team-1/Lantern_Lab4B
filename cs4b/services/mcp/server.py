"""Part 2 (Lab 34B): the read-only MCP query server.

Four READ tools, a closed catalog, one read-only connection (gate.connect_ro:
mode=ro + authorizer), every query through gate.run_query, and a ledger event
for every call and every refusal.

    mcp dev services/mcp/server.py          # the Inspector
"""
import hashlib
import os
import sys
from pathlib import Path
from typing import Union

import yaml
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT, ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from mcp.server import MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

from agent.contract import ColumnInfo, QueryResult  # noqa: E402
from askpanel import audit, clock, gate  # noqa: E402
from askpanel.tools import DESCRIPTIONS  # noqa: E402

# ------------------------------------------------------------------ settings
P = yaml.safe_load((ROOT / "params.yaml").read_text())
DB = Path(os.environ.get("ASKPANEL_DB") or ROOT / P["data"]["db"])
TABLES = tuple(P["server"]["tables"])
MAX_ROWS = int(P["server"]["max_rows"])
TIMEOUT_S = float(P["server"]["timeout_s"])
_LEDGER_PATH = os.environ.get("ASKPANEL_LEDGER", str(ROOT / "outputs" / "ledger.jsonl"))
LEDGER = audit.Ledger(path=_LEDGER_PATH or None, clock=clock.clock)

# The closed catalog: the self-check reads this literal.
REGISTRY = {
    "list_tables": "READ",
    "describe_table": "READ",
    "sample_values": "READ",
    "run_query": "READ",
}

# ------------------------------------------------------------------ output models
Cell = Union[str, int, float, None]


class TableList(BaseModel):
    tables: list[str]


class TableDescription(BaseModel):
    table: str
    columns: list[ColumnInfo]


class SampleValues(BaseModel):
    table: str
    column: str
    values: list[Cell]


# ------------------------------------------------------------------ connection and helpers
_CON = None


def con():
    """One read-only connection with the authorizer, opened on first use."""
    global _CON
    if _CON is None:
        try:
            _CON = gate.connect_ro(DB, set(TABLES))
        except FileNotFoundError:
            raise ToolError(f"no database at {DB}: run python tools/build_db.py") from None
    return _CON


def _refuse(tool, e, **fields):
    """Record the refusal, then raise it so the client sees is_error."""
    LEDGER.record("policy_block", tool=tool, code=e.code, **fields)
    raise ToolError(f"{e.code}: {e.detail}") from None


def _columns(table):
    if table not in TABLES:
        raise gate.GateError("not_authorized", f"unknown table {table!r}")
    cur = con().execute(f'SELECT * FROM "{table}" LIMIT 0')
    return [d[0] for d in cur.description]


def _h12(text):
    return hashlib.sha256(text.encode()).hexdigest()[:12]


mcp = MCPServer("askpanel-query")


# ------------------------------------------------------------------ the four tools
@mcp.tool()
def list_tables() -> TableList:
    """List the tables and views you may query (READ)."""
    LEDGER.record("tool_call", tool="list_tables")
    return TableList(tables=list(TABLES))


@mcp.tool()
def describe_table(table: str) -> TableDescription:
    """Columns of one table, each with a description (READ)."""
    try:
        cols = _columns(table)
    except gate.GateError as e:
        _refuse("describe_table", e, table=table)
    LEDGER.record("tool_call", tool="describe_table", table=table)
    return TableDescription(table=table, columns=[
        ColumnInfo(column=c, description=DESCRIPTIONS.get(c, "")) for c in cols])


@mcp.tool()
def sample_values(table: str, column: str, limit: int = 20) -> SampleValues:
    """Distinct values of one column, to get exact names before filtering (READ)."""
    limit = max(1, min(int(limit), 100))
    try:
        if column not in _columns(table):
            raise gate.GateError("invalid", f"no column {column!r} in {table}")
        r = gate.run_query(con(), f'SELECT DISTINCT "{column}" FROM "{table}" '
                                  f'WHERE "{column}" IS NOT NULL ORDER BY 1 LIMIT {limit}',
                           max_rows=limit, timeout_s=TIMEOUT_S)
    except gate.GateError as e:
        _refuse("sample_values", e, table=table, column=column)
    LEDGER.record("tool_call", tool="sample_values", table=table, column=column,
                  rows=r["row_count"])
    return SampleValues(table=table, column=column, values=[row[0] for row in r["rows"]])


@mcp.tool()
def run_query(sql: str) -> QueryResult:
    """Run ONE SELECT (READ). Refused unless read-only; rows capped; timed out."""
    try:
        r = gate.run_query(con(), sql, max_rows=MAX_ROWS, timeout_s=TIMEOUT_S)
    except gate.GateError as e:
        _refuse("run_query", e, sql_hash=_h12(sql or ""))
    LEDGER.record("tool_call", tool="run_query", sql_hash=_h12(r["sql"]),
                  rows=r["row_count"], truncated=r["truncated"], ms=r["ms"])
    return QueryResult(**r)


if __name__ == "__main__":
    mcp.run()