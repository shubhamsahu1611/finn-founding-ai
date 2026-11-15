# FINN · Founding AI Engineer

FINN is a mobile-first investment desk for Indian equities. It brings together a watchlist brief, alerts, source-linked research, and a fictional contact network that helps an investor decide who to ask about a filing.

- [Features and architecture](FEATURES.md)
- [AI conversation excerpts](AI_CONVERSATION.md)

## Run it

Use Python 3.13. From the repository root on Windows:

```powershell
.\run.ps1
```

On macOS or Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn finn.main:app --host 127.0.0.1 --port 8000
```

Open [FINN](http://127.0.0.1:8000) or the [API documentation](http://127.0.0.1:8000/docs). The first visit fetches public data. Later visits open the saved snapshot and can refresh sources manually.

## Open it on a phone

Connect the computer and phone to the same trusted Wi-Fi. Run `.\run.ps1 -Lan` on Windows and open the **Phone** URL it prints. On macOS or Linux, start Uvicorn with `--host 0.0.0.0` and open the computer’s Wi-Fi IP on port 8000.

For HTTPS hosting, connect the repository to a Render Blueprint using [render.yaml](render.yaml). If you add a custom Cloudflare domain, set `FINN_ALLOWED_ORIGINS` to that exact HTTPS origin. The free Render setup uses temporary storage. Mount persistent storage and set `FINN_DB` to a path on it if the deployment needs to retain notes and preferences across restarts. Use sample data for public demos since visitors share one workspace.

## Optional Gemini analysis

Set `GEMINI_API_KEY` in the server environment and restart FINN. **Analyze with AI**, **Analyze filing with AI**, and **Listen** can call Gemini 3.1 Flash-Lite. Public-source research, alerts, price checks, and Network matching are available with the default configuration. See [.env.example](.env.example) for environment settings.

## Verify

```powershell
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest -q
node --test tests/desk.test.cjs
```

On macOS or Linux, use `.venv/bin/python` in the Python commands. Node.js is needed only for the JavaScript tests.
