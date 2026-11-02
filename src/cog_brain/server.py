"""MCP compatibility adapter; application operations also power the Python API."""
import sys
import inspect
from functools import wraps
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent
from cog_brain.operations import *  # preserve existing direct-import consumers
from cog_brain import operations

mcp = FastMCP("cog-brain")


def _adapter(fn):
    @wraps(fn)
    def call(*args, **kwargs):
        try:
            text = fn(*args, **kwargs)
            error = text.startswith(("error:", "not found:"))
            try:
                value = json.loads(text)
            except ValueError:
                value = {"text": text}
            if not isinstance(value, dict):
                value = {"hits": value}
            return CallToolResult(content=[TextContent(type="text", text=text)],
                                  structuredContent=value, isError=error)
        except Exception as error:
            return CallToolResult(content=[TextContent(type="text", text=f"error: {error}")], isError=True)
    call.__signature__ = inspect.signature(fn).replace(return_annotation=CallToolResult)
    return call


for _name in ("vault_status", "list_notes", "outline", "read_note", "semantic_search",
              "find_related", "backlinks", "broken_links", "graph_overview",
              "write_note", "update_note", "index_now"):
    mcp.add_tool(_adapter(getattr(operations, _name)), structured_output=False)

# --------------------------------------------------------------------------- simple HTTP API

def serve_simple_http():
    """Plain JSON API for nvim/curl: POST /search {"query":..., "k":8} -> results."""
    from http.server import BaseHTTPRequestHandler, HTTPServer
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
            if self.path.rstrip("/") == "/status":
                res = vault_status()
            else:
                res = semantic_search(req.get("query", ""), req.get("k", 8), req.get("tag"),
                                      req.get("folder"), req.get("chunks_per_note", 1))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(res.encode())
        def log_message(self, *a): pass
    print("simple http on 127.0.0.1:8766")
    HTTPServer(("127.0.0.1", 8766), H).serve_forever()

def main() -> None:
    # `cog-brain <op>` runs the operator CLI; a bare `cog-brain` (what MCP clients
    # spawn) serves the MCP stdio server.
    ops = {"status", "config", "doctor", "backends", "reindex", "health", "lint", "graph",
           "inspect", "ingest", "mcp-config", "install", "call", "context", "hook"}
    if any(tok in ops for tok in sys.argv[1:]):
        from cog_brain import cli
        cli.main()
        return
    if "--simple-http" in sys.argv:
        serve_simple_http()
    elif "--http" in sys.argv:
        mcp.settings.host = "127.0.0.1"
        mcp.settings.port = 8765
        mcp.run(transport="sse")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
