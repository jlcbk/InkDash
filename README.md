# KindleVibe-Python

A Kindle-friendly dashboard for monitoring AI coding tool usage, written in Python.

Port of [KindleVibe](https://github.com/lexrus/KindleVibe) (original Go version by lexrus).

## Features

- **Kindle optimized**: High-contrast, large typography, portrait-friendly layout (e-ink)
- **Multi-provider**: Codex + GitHub Copilot usage on one dashboard
- **Segment bars**: 10-segment meters matching the original KindleVibe design
- **Auto-refresh**: Page refreshes every 5 minutes (configurable)
- **Web-based settings**: Configure the app directly from the browser
- **Logging**: Detailed logs for debugging
- **Modular**: Clean Python modules for each provider
- **No Go required**: Just Python 3

## Prerequisites

- Python 3.7 or later
- **Codex CLI**: `npm install -g @openai/codex` (optional — only if monitoring Codex)
- **GitHub Copilot**: Authenticated locally (optional — only if monitoring Copilot)

## Quick Start

```bash
python3 app.py
```

Open `http://<your-local-ip>:8080` on your Kindle.

## File Structure

```
app.py          # HTTP server and main entry point
config.py       # Configuration manager (singleton)
cache.py        # Throttle cache for rate-limited fetches
codex.py        # Codex usage provider (CLI RPC + session files)
copilot.py      # Copilot usage provider (GitHub API)
templates.py    # HTML generation (segment bars, settings page)
config.json     # User settings
logs/           # Log output (auto-created)
```

## Providers

### Codex
- Fetches from `codex app-server` JSON-RPC (preferred)
- Falls back to `~/.codex/sessions/` files
- Shows 5-hour and weekly rate-limit usage bars

### GitHub Copilot
- Reads token from `config.json` → `COPILOT_API_TOKEN` env → `~/.config/github-copilot/apps.json`
- Fetches from `api.github.com/copilot_internal/user`
- Shows Premium and Chat quota bars

## Configuration

Web UI at `/settings` or edit `config.json` directly:

```json
{
  "server": { "port": 8080, "host": "0.0.0.0" },
  "refresh": { "interval_seconds": 300, "page_refresh_ms": 300000 },
  "codex": { "enabled": true, "source": "auto", "session_file_limit": 10 },
  "copilot": { "enabled": true, "token": "" },
  "display": { "show_credits": true, "show_plan_type": true }
}
```

## API

- `GET /api/usage` — JSON usage for all providers
- `GET /api/config` — JSON config dump

## License

WTFPL (same as original KindleVibe)
