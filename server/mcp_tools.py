#!/usr/bin/env python3
"""Tiny MCP server (stdio) that gives Claude / Codex two tools: run_python and run_lean.

It does not run anything itself: it forwards each call to server.py's private
executor on 127.0.0.1 (TOOLS_URL), which runs the code in a locked-down sandbox.
Standard library only, so it works with the system python3.
"""

import json
import os
import sys
import urllib.request

URL = os.environ.get("TOOLS_URL", "http://127.0.0.1:8788/run")
SECRET = os.environ.get("TOOLS_SECRET", "")

TOOLS = [
    {
        "name": "run_python",
        "description": (
            "Run a Python 3.12 script and get its stdout/stderr. Use it to compute, check "
            "algebra, test code, or explore numerically. Installed: numpy, scipy, sympy, "
            "mpmath, networkx, pandas, matplotlib (Agg backend; images can't be shown), "
            "z3-solver. No internet and no file access outside a scratch folder. "
            "Print anything you want to see. Time limit about 60 seconds."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "Complete Python script"}},
            "required": ["code"],
            "additionalProperties": False,
        },
    },
    {
        "name": "run_lean",
        "description": (
            "Check a Lean 4 file (Lean v4.36, with Mathlib). Returns Lean's messages: errors, "
            "warnings, and output of #eval / #check / #print. No output and exit code 0 means "
            "everything type-checked. Use it to verify proofs and definitions. "
            "IMPORTANT: this computer is slow to load Mathlib. Import only the modules you need "
            "(e.g. `import Mathlib.Tactic`, `import Mathlib.Analysis.SpecialFunctions.Pow.Real`): "
            "that takes ~40s, while `import Mathlib` takes ~2 minutes. Put several checks in one "
            "file rather than calling the tool many times. Time limit 5 minutes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "Complete Lean 4 file"}},
            "required": ["code"],
            "additionalProperties": False,
        },
    },
]


def call_executor(lang, code):
    body = json.dumps({"lang": lang, "code": code}).encode()
    req = urllib.request.Request(URL, data=body, headers={
        "Content-Type": "application/json", "X-Tools-Secret": SECRET})
    with urllib.request.urlopen(req, timeout=400) as r:
        return json.loads(r.read())


def format_result(res):
    parts = []
    if res.get("timed_out"):
        parts.append("[stopped: time limit reached]")
    if res.get("killed_for_memory"):
        parts.append("[stopped: memory limit reached]")
    if res.get("stdout"):
        parts.append(res["stdout"])
    if res.get("stderr"):
        parts.append("[stderr]\n" + res["stderr"])
    parts.append("[exit code %s]" % res.get("exit_code"))
    return "\n".join(parts)


def handle(msg):
    method = msg.get("method")
    params = msg.get("params") or {}
    if method == "initialize":
        return {"protocolVersion": params.get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "laptop-tools", "version": "1.0"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        name = params.get("name")
        code = (params.get("arguments") or {}).get("code", "")
        lang = {"run_python": "python", "run_lean": "lean"}.get(name)
        if not lang:
            raise ValueError("unknown tool %r" % name)
        try:
            res = call_executor(lang, code)
            text, err = format_result(res), res.get("exit_code") != 0
        except Exception as e:
            text, err = "Tool error: %s" % e, True
        return {"content": [{"type": "text", "text": text}], "isError": err}
    raise LookupError(method)


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if "id" not in msg:          # notification, e.g. notifications/initialized
            continue
        try:
            out = {"jsonrpc": "2.0", "id": msg["id"], "result": handle(msg)}
        except LookupError:
            out = {"jsonrpc": "2.0", "id": msg["id"],
                   "error": {"code": -32601, "message": "method not found"}}
        except Exception as e:
            out = {"jsonrpc": "2.0", "id": msg["id"],
                   "error": {"code": -32000, "message": str(e)}}
        sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
