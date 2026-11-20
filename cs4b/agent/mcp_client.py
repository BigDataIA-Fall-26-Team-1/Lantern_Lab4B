"""Part 2 (Lab 34B): synchronous access to the MCP query server.

LangGraph nodes and Streamlit are synchronous; the MCP SDK client is async.
McpTools keeps ONE session open on an event loop in a background thread and
turns each tool into a plain function. The agent reaches data only this way.

    tools = McpTools(server.mcp).as_node_tools()
    tools["run_query"](sql="SELECT ...")
"""
import asyncio
import re
import threading

from mcp import Client

_CODES = ("empty", "not_select", "multiple_statements", "not_authorized",
          "invalid", "timeout")
_CODE_RE = re.compile(r"\b(" + "|".join(_CODES) + r"):\s*(.*)", re.S)


class ToolCallError(Exception):
    """A tool call the server refused. .code is the gate's code."""

    def __init__(self, tool, text):
        m = _CODE_RE.search(text)
        self.tool = tool
        self.code = m.group(1) if m else "tool_error"
        self.detail = m.group(2).strip() if m else text
        super().__init__(f"{self.code}: {self.detail}")


class McpTools:
    """One long-lived MCP session on a background event loop."""

    def __init__(self, server, timeout_s=30):
        self.timeout_s = timeout_s
        self._error = None
        self._ready = threading.Event()
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True).start()
        self._task = asyncio.run_coroutine_threadsafe(self._hold(server), self._loop)
        if not self._ready.wait(timeout_s):
            raise RuntimeError("the MCP session did not open")
        if self._error:
            raise self._error

    async def _hold(self, server):
        # Open AND close the Client in this same task (else a cancel-scope error).
        self._stop = asyncio.Event()
        try:
            async with Client(server) as client:
                self._client = client
                self._ready.set()
                await self._stop.wait()
        except Exception as e:  # noqa: BLE001
            self._error = e
            self._ready.set()

    def call(self, name, **args):
        fut = asyncio.run_coroutine_threadsafe(
            self._client.call_tool(name, args), self._loop)
        r = fut.result(self.timeout_s)
        if r.is_error:
            text = " ".join(getattr(c, "text", "") for c in r.content)
            raise ToolCallError(name, text)
        return r.structured_content

    def as_node_tools(self):
        """The four tools in the shapes askpanel.nodes expects."""
        return {
            "list_tables": lambda: self.call("list_tables")["tables"],
            "describe_table": lambda table: self.call(
                "describe_table", table=table)["columns"],
            "sample_values": lambda table, column, limit=20: self.call(
                "sample_values", table=table, column=column, limit=limit)["values"],
            "run_query": lambda sql: self.call("run_query", sql=sql),
        }

    def close(self):
        self._loop.call_soon_threadsafe(self._stop.set)
        self._task.result(self.timeout_s)
        self._loop.call_soon_threadsafe(self._loop.stop)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()