"""Part 1 tests: pytest -q tests/test_contract.py (no database needed)."""
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from agent.contract import (QueryRequest, QueryResult, SchemaCatalog,  # noqa: E402
                            SQLQuery, validate_query)
from askpanel import nodes  # noqa: E402


# ------------------------------------------------------------------ the five required refusals
@pytest.mark.parametrize("d, code", [
    ({"sql": "DELETE FROM holdings"}, "not_select"),
    ({"sql": "SELECT 1; SELECT 2"}, "multiple_statements"),
    ({"sql": "SELECT * FROM sqlite_master"}, "not_authorized"),
    ({"sql": "SELECT bdc FROM holdings_v", "decline": "no"}, "invalid"),   # both set
    ({"sql": None, "decline": None}, "invalid"),                           # neither set
])
def test_refusals_carry_the_code(d, code):
    model, err = validate_query(d)
    assert model is None
    assert err["code"] == code, err
    assert err["detail"]


def test_more_refusals():
    for sql, code in [("WITH x AS (SELECT 1) DELETE FROM holdings", "not_select"),
                      ("SELECT * FROM holdings_v h JOIN secrets s ON 1", "not_authorized"),
                      ("   ", "empty")]:
        assert validate_query({"sql": sql})[1]["code"] == code, sql
    assert validate_query({"sql": "SELECT 1", "extra": 1})[1]["code"] == "invalid"
    assert validate_query("SELECT 1")[1]["code"] == "invalid"             # not a dict


def test_pydantic_raises_directly():
    with pytest.raises(ValidationError):
        SQLQuery(sql="DROP TABLE holdings")
    with pytest.raises(ValidationError):
        SQLQuery()


# ------------------------------------------------------------------ what passes
def test_select_and_decline_pass():
    m, err = validate_query({"sql": "SELECT bdc, COUNT(*) FROM holdings_v GROUP BY 1;",
                             "explanation": None})
    assert err is None and m.sql.endswith("GROUP BY 1") and m.explanation == ""
    m, err = validate_query({"sql": "SELECT 'a;b' AS x FROM filings"})   # ; inside a string is fine
    assert err is None
    m, err = validate_query({"sql": None, "decline": "The panel has no NAV forecasts."})
    assert err is None and m.sql is None


def test_blank_decline_is_neither():
    assert validate_query({"sql": None, "decline": "  "})[1]["code"] == "invalid"


# ------------------------------------------------------------------ the other three models
def test_query_result():
    r = {"sql": "SELECT 1", "columns": ["bdc", "price"], "rows": [["A", 89.5], ["B", None]],
         "row_count": 2, "truncated": False, "ms": 1.2}
    assert QueryResult(**r).rows[0] == ["A", 89.5]
    with pytest.raises(ValidationError):
        QueryResult(**{**r, "row_count": 3})


def test_schema_catalog():
    cat = SchemaCatalog(tables=[{"table": "holdings_v", "columns": [
        {"column": "bdc", "description": "BDC name"}, {"column": "price"}]}])
    assert cat.to_prompt() == "holdings_v(bdc: BDC name, price)"
    with pytest.raises(ValidationError):
        SchemaCatalog(tables=[{"table": "sqlite_master", "columns": []}])


def test_query_request_mirrors_the_kit():
    req = nodes.build_request(nodes.new_state("How many holdings?"), "gemini-x")
    assert QueryRequest.from_request(req).question == "How many holdings?"