# Ask My Laptop

A public web page (hosted free on GitHub Pages) where visitors pick an AI model and ask a question.
The question travels to a small server on this laptop, which forwards it to **Claude** (Anthropic API)
or **Codex** (OpenAI API) and streams the answer back.

```
visitor's browser ──► GitHub Pages site (docs/)
        │
        └──► https://hoais-macbook-air.tailbeb7c7.ts.net:8443   (Tailscale Funnel)
                 └──► server.py on this laptop (127.0.0.1:8787)
                          ├──► Anthropic API  (Claude models)
                          └──► OpenAI API     (Codex)
```

**Safety:** the models are called through their cloud APIs with no tools, so they cannot read files or run
commands on this laptop. They only see the base prompt, your `rules.md`, and the visitor's messages.

## Everyday use

```bash
~/ask-my-laptop/server/start.sh     # start server + open the public tunnel (Ctrl+C to stop the server)
~/ask-my-laptop/server/stop.sh      # close the public tunnel
```

The site shows a red dot ("server offline") whenever the server isn't running or the laptop is asleep.

## Files you'll edit

| File | What it does |
|---|---|
| `server/rules.md` | Your instructions for the AI (e.g. reply "tsk tsk tsk nice try" to questions about you). Applied on the next question, no restart. |
| `server/models.json` | Which models appear in the dropdown. Set `"enabled": false` to hide one. Applied live. |
| `server/.env` | API keys, access code, rate limits, allowed website origin. Restart after editing. |
| `docs/` | The website. Push to GitHub to update it. |

## Settings in `server/.env`

- `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` — models for a provider only show up when its key is set.
- `ACCESS_CODE` — if set, visitors must type it before asking (stops strangers spending your credits).
- `PER_IP_PER_MINUTE`, `PER_IP_PER_DAY`, `GLOBAL_PER_DAY` — spending guards.
- `ALLOWED_ORIGINS` — which websites may call the server (your `https://<user>.github.io`).
- `LOG_QUESTIONS` — questions/answers are saved to `server/logs/requests.jsonl` (IPs are hashed).
- `REFUSAL_REPLY` — shown when the AI provider itself refuses a request.

## Useful commands

```bash
cd ~/ask-my-laptop/server && .venv/bin/python server.py --check               # which keys/models are active
cd ~/ask-my-laptop/server && .venv/bin/python server.py --list-openai-models  # find current Codex model names
```
