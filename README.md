# KindleVibe-Python

A Kindle-friendly dashboard for monitoring Codex usage, written in Python.

## Features

- **Kindle optimized**: High-contrast, large typography, portrait-friendly layout
- **Real-time data**: Fetches usage from Codex CLI via JSON-RPC (falls back to session files)
- **Auto-refresh**: Page refreshes every 5 minutes (configurable)
- **Web-based settings**: Configure the app directly from the browser
- **Logging**: Detailed logs for debugging
- **Simple setup**: No Go required, just Python 3

## Prerequisites

- Python 3.7 or later
- Codex CLI installed and authenticated (`npm install -g @openai/codex`)

## Quick Start

1. **Clone or download this project**

2. **Run the server**

   ```bash
   python3 app.py
   ```

   Or with custom port:

   ```bash
   python3 app.py --port 9090
   ```

3. **Open in Kindle browser**

   Visit: `http://<your-local-ip>:8080`

## Configuration

### Config File

Configuration is stored in `config.json` and can be edited:
- Manually with a text editor
- Through the web interface (click "Settings" button)

### Config Options

```json
{
  "server": {
    "port": 8080,           // Server port
    "host": "0.0.0.0"       // Server bind address
  },
  "refresh": {
    "interval_seconds": 300,      // Data refresh interval (30-3600)
    "auto_refresh_page_ms": 300000  // Page auto-refresh (ms)
  },
  "codex": {
    "enabled": true,              // Enable Codex monitoring
    "source": "auto",             // "auto", "cli", or "session"
    "session_file_limit": 10      // Max session files to scan
  },
  "display": {
    "show_credits": true,
    "show_plan_type": true,
    "show_data_source": true,
    "show_last_updated": true
  }
}
```

## Web Interface

### Dashboard (`/`)
- Shows Codex usage (5h limit, weekly limit)
- Displays account info (plan, credits, data source)
- Settings button in top-right corner

### Settings (`/settings`)
- Server settings (port, host)
- Refresh settings (interval, page refresh)
- Codex settings (enabled, data source, session limit)
- Display settings (what to show/hide)

### API Endpoints
- `GET /api/usage` - JSON usage data
- `GET /api/config` - JSON configuration

## Data Sources

1. **Codex CLI RPC** (preferred): Uses `codex app-server` for real-time data
2. **Session files** (fallback): Reads from `~/.codex/sessions/` directory

## Logging

Logs are stored in `logs/kindlevibe.log` with detailed information for debugging.

## Troubleshooting

### "codex not found in PATH"

Make sure Codex CLI is installed and in your PATH:

```bash
npm install -g @openai/codex
codex --version
```

### Usage data not updating

- Check `logs/kindlevibe.log` for errors
- Ensure you have an active Codex subscription
- Try changing data source to "session" in settings

## License

WTFPL (same as original KindleVibe)
