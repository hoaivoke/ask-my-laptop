# Ask My Laptop

A public web page (hosted free on GitHub Pages) where visitors pick an AI model and ask a question.
The question travels to a small server on this laptop, which runs the **Claude Code** (`claude`) or
**Codex** (`codex`) command-line tool, using the laptop owner's subscriptions, and streams the answer back.

```
visitor's browser ──► GitHub Pages site (docs/)
        │
        └──► https://hoais-macbook-air.tailbeb7c7.ts.net:8443   (Tailscale Funnel)
                 └──► server.py on this laptop (127.0.0.1:8787)
                          ├──► claude -p   (Claude Opus / Sonnet / Haiku)
                          └──► codex exec  (Codex)
```

## Models and tools

- `server/models.json` lists every Claude model the subscription can use (13) and every Codex model (8).
- The AI can use two tools for math and coding: **run_python** (Python 3.12 with numpy, scipy, sympy,
  mpmath, networkx, pandas, matplotlib, z3) and **run_lean** (Lean 4 + Mathlib). Each run shows up in the
  chat as a collapsible box with the code and output. Installed under `server/runtime/tools/` (~10 GB).
- On this 8 GB laptop, Lean with `import Mathlib` takes ~2 minutes; narrower imports take ~40 s.

## Access code

If `ACCESS_CODE` is set in `server/.env`, visitors type it once per browser tab; the server hands back a
session that lasts `SESSION_HOURS` (default 24). 5 wrong codes from one address locks it out for 10 minutes.

## Lockdown

The CLIs are agents that can normally run commands and read files, so every run is restricted:

1. **Only our tools.** Claude runs with `--tools ""` (no built-in tools), no settings or slash commands, and
   only the `run_python` / `run_lean` MCP tools from `server/mcp_tools.py`. Codex runs with its shell,
   code-mode, browser, computer-use, plugin, and sub-agent features off, plus the same two tools.
2. **Separate config.** The server's Claude and Codex use their own login and settings in
   `server/runtime/`, so your personal CLI config, plugins, and chat history are never loaded.
3. **macOS sandbox.** Each CLI run is wrapped in `sandbox-exec` with a profile that blocks reading or
   writing anything in your home folder except `server/runtime/`.
4. **Stricter sandbox for code.** Python/Lean code runs through a private runner (127.0.0.1:8788, secret
   per server start, not reachable from the internet) inside a sandbox with no network, no access to
   /Users except the tools, no other programs, a scratch folder only, and time limits (`server/executor.py`).

## Running it

The server is installed as a login service (`~/Library/LaunchAgents/com.askmylaptop.server.plist`):
it starts when you log in and restarts itself if it crashes. Output goes to `server/logs/server.log`.

```bash
launchctl kickstart -k gui/$(id -u)/com.askmylaptop.server     # restart (after editing .env)
launchctl bootout gui/$(id -u)/com.askmylaptop.server           # stop and disable until next login
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.askmylaptop.server.plist   # start again
~/ask-my-laptop/server/stop.sh                                  # close the public tunnel
```

## Files you'll edit

| File | What it does |
|---|---|
| `server/rules.md` | Your instructions for the AI (e.g. reply "tsk tsk tsk nice try" to questions about you). Applied on the next question, no restart. |
| `server/models.json` | Which models appear in the dropdown. Set `"enabled": false` to hide one. Applied live. |
| `server/.env` | Claude token, access code, rate limits, allowed website origin. Restart after editing. |
| `docs/` | The website. Push to GitHub to update it. |

## Logins

- **Claude:** `claude setup-token`, then put the token in `server/.env` as `CLAUDE_CODE_OAUTH_TOKEN=`.
- **Codex:** `CODEX_HOME=~/ask-my-laptop/server/runtime/codex-home /Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex login --device-auth`

## Useful commands

```bash
cd ~/ask-my-laptop/server && python3 server.py --check                    # which CLIs/models are active
cd ~/ask-my-laptop/server && python3 server.py --ask claude-haiku "hi"    # test a model without the website
```
