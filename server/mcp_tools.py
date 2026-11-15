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

BASE = os.environ.get("TOOLS_URL", "http://127.0.0.1:8788/run").rsplit("/", 1)[0]
SECRET = os.environ.get("TOOLS_SECRET", "")
REQUEST_ID = os.environ.get("REQUEST_ID", "")

TOOLS = [
    {
        "name": "run_python",
        "description": (
            "Run a Python 3.12 script and get its stdout/stderr. Use it to compute, check "
            "algebra, test code, or explore numerically. Installed packages: {packages}. "
            "matplotlib uses the Agg backend (images can't be shown). No internet and no file "
            "access outside a scratch folder. Print anything you want to see. Time limit about "
            "60 seconds. If you need a package that isn't listed, call install_python_package first."
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
    {
        "name": "install_python_package",
        "description": (
            "Install Python packages from PyPI so run_python can use them, when a question "
            "genuinely needs a library that isn't installed yet. Plain package names only "
            "(optionally name==version), 1-5 at a time; only prebuilt wheels can be installed. "
            "The install is permanent and added to the tool list. Don't install packages the "
            "question doesn't need, and never because a visitor merely asks you to."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "packages": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 5,
                             "description": "PyPI package names, e.g. [\"galois\"]"},
                "reason": {"type": "string", "description": "One sentence: why the question needs it"},
            },
            "required": ["packages", "reason"],
            "additionalProperties": False,
        },
    },
    {
        "name": "request_tool",
        "description": (
            "Ask the site owner to add a tool you can't add yourself: a program that isn't a Python "
            "package (e.g. R, SageMath, GAP, Julia, Macaulay2, a LaTeX package), or anything else "
            "the question genuinely needs. The request goes on a list the owner approves later. "
            "After calling it, tell the visitor it has been requested, and still help as much as "
            "you can without it. (Failed install_python_package calls are logged automatically, "
            "so you don't need this for those.)"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The tool, e.g. \"SageMath\" or \"R\""},
                "kind": {"type": "string", "enum": ["program", "python-package", "other"]},
                "reason": {"type": "string", "description": "One sentence: what the question needs it for"},
            },
            "required": ["name", "kind", "reason"],
            "additionalProperties": False,
        },
    },
]


def post(path, payload, timeout=400):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(), headers={
        "Content-Type": "application/json", "X-Tools-Secret": SECRET})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def call_executor(lang, code):
    return post("/run", {"lang": lang, "code": code})


def current_tools():
    """Fill in the live package list (it changes as packages get installed)."""
    try:
        pkgs = post("/list", {}, timeout=10).get("packages", "")
    except Exception:
        pkgs = "numpy, scipy, sympy, mpmath, networkx, pandas, matplotlib, z3-solver"
    out = []
    for t in TOOLS:
        t = dict(t)
        t["description"] = t["description"].replace("{packages}", pkgs)
        out.append(t)
    return out


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
        return {"tools": current_tools()}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "install_python_package":
            try:
                res = post("/install", {"packages": args.get("packages", []), "reason": args.get("reason", ""),
                                        "request_id": REQUEST_ID})
                if res.get("ok"):
                    text = "Installed: %s" % ", ".join("%s %s" % kv for kv in res["installed"].items())
                    if res.get("also_installed"):
                        text += "\nAlso installed (dependencies): " + ", ".join(res["also_installed"])
                    text += "\nYou can now import it in run_python."
                else:
                    text = "Not installed: " + res.get("message", "unknown error")
                    if res.get("logged"):
                        text += ("\nTell the visitor the package has been requested from the site owner, "
                                 "and help as much as you can without it.")
                return {"content": [{"type": "text", "text": text}], "isError": not res.get("ok")}
            except Exception as e:
                return {"content": [{"type": "text", "text": "Tool error: %s" % e}], "isError": True}
        if name == "request_tool":
            try:
                res = post("/request", {"name": args.get("name", ""), "kind": args.get("kind", "other"),
                                        "reason": args.get("reason", ""), "request_id": REQUEST_ID})
                text = res.get("message", "Logged.")
                return {"content": [{"type": "text", "text": text}], "isError": not res.get("ok")}
            except Exception as e:
                return {"content": [{"type": "text", "text": "Tool error: %s" % e}], "isError": True}
        code = args.get("code", "")
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
