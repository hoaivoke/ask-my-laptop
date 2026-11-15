#!/bin/zsh
# Closes ONLY this project's public tunnel (port 8443). Your other Tailscale serve settings are untouched.
/Applications/Tailscale.app/Contents/MacOS/Tailscale funnel --https=8443 off && echo "Public tunnel closed."
