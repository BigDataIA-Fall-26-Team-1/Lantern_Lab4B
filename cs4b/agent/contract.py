"""Part 1 (Lab 33B): the typed contract between the model, the agent and the server.

    SchemaCatalog  what load_schema shows the model (tables, columns, descriptions)
    QueryRequest   the exact request the generate node sends (mirrors nodes.build_request)
    SQLQuery       the model's answer: ONE gated SELECT, or a reason to decline
    QueryResult    the server's reply to run_query (mirrors gate.run_query)

validate_query(d) -> (SQLQuery, None) or (None, {"code": ..., "detail": ...}),
with the gate's code, so the check node can send it to the repair edge.
No database here: the server's gate stays the authority.
"""
import sys
from pathlib import Path
from typing import Any, Optional, Union

from pydantic import (BaseModel, ConfigDict, ValidationError, field_validator,
                      model_validator)

# so `python agent/run.py` can import askpanel from src/
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
from askpanel import gate  # noqa: E402


class ContractError(ValueError):
    """A contract rule broken (not a gate rule), with a code like GateError's."""

    def __init__(self, code, detail):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


# ------------------------------------------------------------------ the model's answer
class SQLQuery(BaseModel):
    """The model's answer: ONE gated SELECT, or a reason to decline."""
    model_config = ConfigDict(extra="forbid")   # reject unknown keys

    sql: Optional[str] = None
    decline: Optional[str] = None
    explanation: str = ""

    @field_validator("sql")
    @classmethod
    def gated(cls, v):
        # Rule 1: the gate's static check (GateError is a ValueError)
        return None if v is None else gate.static_check(v)

    @field_validator("decline", mode="before")
    @classmethod
    def blank_is_none(cls, v):
        # treat "" as no decline, same as the kit's check node
        return None if v is None or not str(v).strip() else v

    @field_validator("explanation", mode="before")
    @classmethod
    def null_is_empty(cls, v):
        # Gemini may send null here
        return "" if v is None else v

    @model_validator(mode="after")
    def exactly_one(self):
        # Rule 2: sql xor decline
        if self.sql is None and self.decline is None:
            raise ContractError("invalid", "reply had neither sql nor decline")
        if self.sql is not None and self.decline is not None:
            raise ContractError("invalid", "reply had both sql and decline")
        return self


# ------------------------------------------------------------------ schema
class ColumnInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str
    description: str = ""


class TableInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table: str
    columns: list[ColumnInfo]


class SchemaCatalog(BaseModel):
    """The tables the model may query, as describe_table reports them."""
    model_config = ConfigDict(extra="forbid")
    tables: list[TableInfo]

    @field_validator("tables")
    @classmethod
    def in_catalog(cls, v):
        bad = sorted({t.table for t in v} - set(gate.ALLOWED_TABLES))
        if bad:
            raise ContractError("not_authorized", f"tables not in the catalog: {bad}")
        return v

    def to_prompt(self):
        """Same text nodes.load_schema builds, so replay cache keys don't change."""
        return "\n".join(
            f"{t.table}(" + ", ".join(
                f"{c.column}: {c.description}" if c.description else c.column
                for c in t.columns) + ")"
            for t in self.tables)


# ------------------------------------------------------------------ request
class HistoryTurn(BaseModel):
    question: str
    sql: Optional[str] = None


class QueryRequest(BaseModel):
    """What the model sees on one generate call (mirrors nodes.build_request)."""
    model_config = ConfigDict(extra="forbid")
    model: str
    system: str
    schema_text: str = ""        # 'schema' clashes with a BaseModel attribute
    history: list[HistoryTurn] = []
    question: str
    attempt: int = 0
    error: Optional[dict[str, Any]] = None
    prior_sql: Optional[str] = None

    @classmethod
    def from_request(cls, req):
        d = dict(req)
        d["schema_text"] = d.pop("schema", "")
        return cls.model_validate(d)


# ------------------------------------------------------------------ server reply
Cell = Union[str, int, float, None]


class QueryResult(BaseModel):
    """run_query's output (mirrors gate.run_query's dict)."""
    model_config = ConfigDict(extra="forbid")
    sql: str
    columns: list[str]
    rows: list[list[Cell]]
    row_count: int
    truncated: bool
    ms: float

    @model_validator(mode="after")
    def consistent(self):
        if self.row_count != len(self.rows):
            raise ContractError("invalid",
                                f"row_count {self.row_count} != {len(self.rows)} rows")
        return self


# ------------------------------------------------------------------ for the check node
def validate_query(d):
    """(SQLQuery, None) if d passes the contract, else (None, {"code", "detail"})."""
    if not isinstance(d, dict):
        return None, {"code": "invalid",
                      "detail": f"expected a dict, got {type(d).__name__}"}
    try:
        return SQLQuery.model_validate(d), None
    except ValidationError as e:
        err = e.errors()[0]
        exc = (err.get("ctx") or {}).get("error")      # the GateError or ContractError
        if getattr(exc, "code", None):
            return None, {"code": exc.code, "detail": exc.detail}
        # anything else (wrong type, unknown key) counts as invalid
        return None, {"code": "invalid", "detail": err.get("msg", "")}