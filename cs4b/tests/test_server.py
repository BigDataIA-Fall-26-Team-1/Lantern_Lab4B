"""Part 2 tests: pytest -q tests/test_server.py

Every call goes over the MCP protocol, in memory (Client(server.mcp)), against
a scratch database built from the fixture and sql/holdings_v.sql. The demo
database is never touched.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from askpanel import catalog, db  # noqa: E402

# Build the scratch database BEFORE importing the server: it reads these at import.
_TMP = Path(tempfile.mkdtemp())
_PANEL = db.load_panel(ROOT / "data/fixture/panel_2p.csv")
_DB = db.build_db(_PANEL, _TMP / "test.sqlite", (ROOT / "sql/holdings_v.sql").read_text())
os.environ["ASKPANEL_DB"] = str(_DB)
os.environ["ASKPANEL_LEDGER"] = ""          # in memory only: tests write no ledger file

from mcp import Client  # noqa: E402
from services.mcp import server  # noqa: E402


def call(name, args=None):
    async def go():
        async with Client(server.mcp) as c:
            return await c.call_tool(name, args or {})
    return asyncio.run(go())


def tool_names():
    async def go():
        async with Client(server.mcp) as c:
            return [t.name for t in (await c.list_tools()).tools]
    return asyncio.run(go())


def text(r):
    return " ".join(getattr(c, "text", "") for c in r.content)


# ------------------------------------------------------------------ the catalog is closed
def test_catalog_is_closed():
    assert catalog.conformance(server.REGISTRY) == []
    assert sorted(tool_names()) == sorted(server.REGISTRY)    # nothing registered beyond the four


# ------------------------------------------------------------------ the READ tools work
def test_list_and_describe():
    r = call("list_tables")
    assert not r.is_error
    assert r.structured_content["tables"] == ["holdings_v", "filings", "holdings"]
    r = call("describe_table", {"table": "holdings_v"})
    cols = r.structured_content["columns"]
    assert [c["column"] for c in cols] == db.VIEW_COLUMNS
    assert all(c["description"] for c in cols)               # the model reads these


def test_sample_values():
    r = call("sample_values", {"table": "filings", "column": "name"})
    assert not r.is_error and len(r.structured_content["values"]) == 4


def test_select_works():
    r = call("run_query", {"sql": "SELECT bdc, COUNT(*) AS n FROM holdings_v GROUP BY 1"})
    assert not r.is_error, text(r)
    assert r.structured_content["row_count"] == 4             # four fixture BDCs
    assert server.LEDGER.find("tool_call", tool="run_query")


# ------------------------------------------------------------------ writes and escapes are refused
@pytest.mark.parametrize("sql, code", [
    ("INSERT INTO filings (adsh) VALUES ('x')", "not_select"),
    ("DROP TABLE holdings", "not_select"),
    ("ATTACH DATABASE 'x.db' AS x", "not_select"),
    ("PRAGMA table_info(holdings)", "not_select"),
    ("SELECT * FROM sqlite_master", "not_authorized"),
    ("SELECT 1; DELETE FROM holdings", "multiple_statements"),
    ("SELECT * FROM pragma_table_info('holdings')", "not_authorized"),
    ("WITH x AS (SELECT 1) UPDATE filings SET name = 'x'", "not_authorized"),
])
def test_refusals(sql, code):
    r = call("run_query", {"sql": sql})
    assert r.is_error, sql
    assert code in text(r), text(r)
    assert server.LEDGER.find("policy_block", tool="run_query", code=code)


def test_unknown_table_refused():
    r = call("describe_table", {"table": "sqlite_master"})
    assert r.is_error
    assert server.LEDGER.find("policy_block", tool="describe_table", code="not_authorized")
    r = call("sample_values", {"table": "filings", "column": "nope"})
    assert r.is_error and "invalid" in text(r)


def test_nothing_was_written():
    r = call("run_query", {"sql": "SELECT COUNT(*) FROM holdings"})
    assert r.structured_content["rows"] == [[74]]             # still the fixture's 74 rows