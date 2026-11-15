#!/bin/zsh
# Starts the backend and makes it reachable from the internet via Tailscale Funnel.
cd "$(dirname "$0")"
TS=/Applications/Tailscale.app/Contents/MacOS/Tailscale
PORT=$(grep -E '^PORT=' .env 2>/dev/null | cut -d= -f2); PORT=${PORT:-8787}

if [ ! -d .venv ]; then
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
fi

echo "Opening public tunnel (Tailscale Funnel) -> localhost:$PORT"
$TS funnel --bg --https=8443 "$PORT" || { echo "Funnel failed - see README"; exit 1; }
$TS funnel status

# keep the Mac awake while the server runs (stops when you Ctrl+C)
exec caffeinate -i .venv/bin/python server.py
