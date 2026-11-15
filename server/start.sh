#!/bin/zsh
# Starts the backend and makes it reachable from the internet via Tailscale Funnel.
cd "$(dirname "$0")"
TS=/Applications/Tailscale.app/Contents/MacOS/Tailscale
PORT=$(grep -E '^PORT=' .env 2>/dev/null | cut -d= -f2); PORT=${PORT:-8787}

echo "Opening public tunnel (Tailscale Funnel, port 8443) -> localhost:$PORT"
$TS funnel --bg --https=8443 "$PORT" >/dev/null || { echo "Funnel failed - is Tailscale running?"; exit 1; }

# keep the Mac from idle-sleeping while the server runs
exec caffeinate -i /usr/bin/python3 -u server.py
