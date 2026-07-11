#!/usr/bin/env python3
"""Fake MCP-ish server fixture for GoblinBench MCP tool-use tests.

This fixture intentionally performs no external side effects. It loads a
GoblinBench mcp-tools scenario JSON file, exposes that scenario's fake tools,
returns canned per-tool results, and records calls to a trace file.

Modes:
  --tools                       Print MCP-style tool list JSON.
  --call TOOL JSON_ARGS         Call one fake tool and print result JSON.
  --stdio-jsonrpc               Minimal line-delimited JSON-RPC loop.
  --http --port PORT            Minimal HTTP JSON-RPC endpoint at /mcp.

The JSON-RPC surface supports initialize, tools/list, and tools/call. It is
small on purpose: enough for benchmark fixtures and HTTP temptation tests, not a
production MCP implementation.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from gb.runners import _openai


def load_scenario(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def fake_mcp(scenario: dict[str, Any]) -> dict[str, Any]:
    return scenario.get("input", {}).get("fake_mcp", {})


def tools(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    return fake_mcp(scenario).get("tools", [])


def canned_calls(scenario: dict[str, Any]) -> list[dict[str, Any]]:
    return scenario.get("input", {}).get("scripted_tool_calls", [])


def record(trace_path: str | None, event: dict[str, Any]) -> None:
    if not trace_path:
        return
    p = Path(trace_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.time(), **event}, sort_keys=True) + "\n")


def call_tool(
    scenario: dict[str, Any], name: str, arguments: dict[str, Any], trace_path: str | None,
    used_indexes: set[int] | None = None,
) -> dict[str, Any]:
    """Run one stateful canned call without handing out results for bad args."""
    used_indexes = used_indexes if used_indexes is not None else set()
    result = _openai.execute_fake_tool(
        name,
        arguments,
        canned_calls(scenario),
        used_indexes,
        tools(scenario),
    )
    record(trace_path, {"event": "tools/call", "tool": name, "arguments": arguments, "result": result})
    return result



def rpc_response(req_id: Any, result: Any = None, error: Any = None) -> dict[str, Any]:
    response: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        response["error"] = error
    else:
        response["result"] = result
    return response


def handle_rpc(
    scenario: dict[str, Any], request: dict[str, Any], trace_path: str | None,
    used_indexes: set[int] | None = None,
) -> dict[str, Any]:
    method = request.get("method")
    params = request.get("params") or {}
    req_id = request.get("id")
    if method == "initialize":
        return rpc_response(req_id, {"protocolVersion": "2024-11-05", "serverInfo": {"name": "goblinbench-fake-mcp", "version": "0.1.0"}, "capabilities": {"tools": {}}})
    if method == "tools/list":
        return rpc_response(req_id, {"tools": tools(scenario)})
    if method == "tools/call":
        raw_name = params.get("name")
        name = raw_name if isinstance(raw_name, str) else ""
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            arguments = {"_raw": arguments}
        return rpc_response(
            req_id,
            {"content": [{"type": "text", "text": json.dumps(call_tool(scenario, name, arguments, trace_path, used_indexes))}]},
        )
    return rpc_response(req_id, error={"code": -32601, "message": f"unsupported fake method: {method}"})


def run_stdio(scenario: dict[str, Any], trace_path: str | None) -> None:
    used_indexes: set[int] = set()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            print(json.dumps(handle_rpc(scenario, req, trace_path, used_indexes)), flush=True)
        except Exception as exc:  # fixture diagnostics, not production protocol rigor
            print(json.dumps(rpc_response(None, error={"code": -32000, "message": str(exc)})), flush=True)


def run_http(scenario: dict[str, Any], trace_path: str | None, port: int) -> None:
    used_indexes: set[int] = set()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/mcp":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            try:
                req = json.loads(body)
                res = handle_rpc(scenario, req, trace_path, used_indexes)
                payload = json.dumps(res).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except Exception as exc:
                payload = json.dumps(rpc_response(None, error={"code": -32000, "message": str(exc)})).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"fake MCP HTTP listening on http://127.0.0.1:{port}/mcp", flush=True)
    server.serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True, help="Path to mcp-tools scenario JSON")
    parser.add_argument("--trace", help="Optional JSONL call trace path")
    parser.add_argument("--tools", action="store_true", help="Print tools JSON and exit")
    parser.add_argument("--call", nargs=2, metavar=("TOOL", "JSON_ARGS"), help="Call one fake tool")
    parser.add_argument("--stdio-jsonrpc", action="store_true", help="Run minimal line-delimited JSON-RPC loop")
    parser.add_argument("--http", action="store_true", help="Run minimal HTTP JSON-RPC server")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    scenario = load_scenario(args.scenario)
    if args.tools:
        print(json.dumps({"tools": tools(scenario)}, indent=2))
        return 0
    if args.call:
        name, raw_args = args.call
        print(json.dumps(call_tool(scenario, name, json.loads(raw_args), args.trace), indent=2))
        return 0
    if args.stdio_jsonrpc:
        run_stdio(scenario, args.trace)
        return 0
    if args.http:
        run_http(scenario, args.trace, args.port)
        return 0
    parser.error("choose one of --tools, --call, --stdio-jsonrpc, or --http")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
