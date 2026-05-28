#!/usr/bin/env python3
"""
KindleVibe-Python: A Kindle-friendly dashboard for Codex usage monitoring.
"""

import re
import subprocess
import json
import logging
import sys
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import threading
import time
from typing import Optional, Dict, Any


# ============================================================================
# Logging Setup
# ============================================================================

def setup_logging():
    """Configure logging with both file and console handlers."""
    logger = logging.getLogger("KindleVibe")
    logger.setLevel(logging.DEBUG)
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(console_format)
    
    # File handler
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "kindlevibe.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_format = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s:%(funcName)s:%(lineno)d - %(message)s"
    )
    file_handler.setFormatter(file_format)
    
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    return logger


logger = setup_logging()


# ============================================================================
# Configuration
# ============================================================================

CONFIG_FILE = Path(__file__).parent / "config.json"

DEFAULT_CONFIG = {
    "server": {
        "port": 8080,
        "host": "0.0.0.0"
    },
    "refresh": {
        "interval_seconds": 300,
        "auto_refresh_page_ms": 300000
    },
    "codex": {
        "enabled": True,
        "source": "auto",
        "session_file_limit": 10
    },
    "display": {
        "show_credits": True,
        "show_plan_type": True,
        "show_data_source": True,
        "show_last_updated": True
    }
}


def load_config() -> Dict[str, Any]:
    """Load configuration from file, creating default if not exists."""
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
            logger.info(f"Configuration loaded from {CONFIG_FILE}")
            # Merge with defaults to ensure all keys exist
            return merge_configs(DEFAULT_CONFIG, config)
        else:
            logger.info("Config file not found, creating default configuration")
            save_config(DEFAULT_CONFIG)
            return DEFAULT_CONFIG.copy()
    except Exception as e:
        logger.error(f"Failed to load config: {e}, using defaults")
        return DEFAULT_CONFIG.copy()


def save_config(config: Dict[str, Any]) -> bool:
    """Save configuration to file."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        logger.info(f"Configuration saved to {CONFIG_FILE}")
        return True
    except Exception as e:
        logger.error(f"Failed to save config: {e}")
        return False


def merge_configs(default: Dict, override: Dict) -> Dict:
    """Deep merge override into default config."""
    result = default.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_configs(result[key], value)
        else:
            result[key] = value
    return result


# Global config
config = load_config()


# ============================================================================
# Codex Usage Data
# ============================================================================

class CodexUsage:
    """Represents Codex usage data."""
    
    def __init__(self):
        self.five_hour_percent_left: int = -1
        self.five_hour_reset: str = ""
        self.weekly_percent_left: int = -1
        self.weekly_reset: str = ""
        self.credits: str = ""
        self.plan_type: str = ""
        self.last_updated: str = ""
        self.source: str = ""  # "cli-rpc" or "session"
        self.error: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "five_hour_percent_left": self.five_hour_percent_left,
            "five_hour_reset": self.five_hour_reset,
            "weekly_percent_left": self.weekly_percent_left,
            "weekly_reset": self.weekly_reset,
            "credits": self.credits,
            "plan_type": self.plan_type,
            "source": self.source,
            "last_updated": self.last_updated,
            "error": self.error
        }


def find_codex_binary() -> Optional[str]:
    """Find the codex binary in PATH."""
    try:
        result = subprocess.run(
            ["which", "codex"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            path = result.stdout.strip()
            logger.debug(f"Found codex binary at: {path}")
            return path
    except Exception as e:
        logger.warning(f"Error finding codex binary: {e}")
    return None


def fetch_codex_status_cli() -> CodexUsage:
    """Fetch Codex usage via JSON-RPC through codex app-server."""
    usage = CodexUsage()
    
    codex_path = find_codex_binary()
    if not codex_path:
        usage.error = "codex not found in PATH"
        logger.error(usage.error)
        return usage
    
    process = None
    try:
        logger.info("Starting codex app-server for RPC...")
        
        # Start codex app-server process
        process = subprocess.Popen(
            [codex_path, "-s", "read-only", "-a", "untrusted", "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Buffer for stdout lines
        stdout_lines = []
        stdout_lock = threading.Lock()
        
        def read_stdout():
            """Read stdout lines in a separate thread."""
            for line in iter(process.stdout.readline, b''):
                with stdout_lock:
                    stdout_lines.append(line)
        
        reader_thread = threading.Thread(target=read_stdout, daemon=True)
        reader_thread.start()
        
        request_counter = [0]
        
        def send_request(method: str, params: Optional[Dict] = None, timeout: float = 3.0) -> Optional[Dict]:
            """Send a JSON-RPC request and wait for response."""
            request_counter[0] += 1
            request_id = request_counter[0]
            request = {
                "id": request_id,
                "method": method,
                "params": params or {}
            }
            
            request_json = json.dumps(request) + "\n"
            process.stdin.write(request_json.encode())
            process.stdin.flush()
            
            logger.debug(f"Sent RPC request: {method} (id={request_id})")
            
            start_time = time.time()
            while time.time() - start_time < timeout:
                with stdout_lock:
                    for line in stdout_lines:
                        try:
                            message = json.loads(line.decode().strip())
                            if "id" not in message:
                                continue
                            if message["id"] == request_id:
                                logger.debug(f"Received RPC response for: {method}")
                                return message
                        except json.JSONDecodeError:
                            continue
                time.sleep(0.1)
            
            logger.warning(f"RPC request timeout: {method}")
            return None
        
        def send_notification(method: str, params: Optional[Dict] = None):
            """Send a JSON-RPC notification (no response expected)."""
            notification = {
                "method": method,
                "params": params or {}
            }
            notification_json = json.dumps(notification) + "\n"
            process.stdin.write(notification_json.encode())
            process.stdin.flush()
            logger.debug(f"Sent RPC notification: {method}")
        
        # Initialize
        init_response = send_request("initialize", {
            "clientInfo": {
                "name": "kindlevibe",
                "version": "1.0.0"
            }
        }, timeout=5.0)
        
        if not init_response or "error" in init_response:
            error_msg = init_response.get("error", {}).get("message", "Unknown error") if init_response else "No response"
            usage.error = f"Failed to initialize: {error_msg}"
            logger.error(usage.error)
            process.terminate()
            return usage
        
        # Send initialized notification
        send_notification("initialized")
        
        # Fetch rate limits
        limits_response = send_request("account/rateLimits/read", timeout=5.0)
        
        # Clean up
        process.terminate()
        process = None
        
        if not limits_response or "error" in limits_response:
            error_msg = limits_response.get("error", {}).get("message", "Unknown error") if limits_response else "No response"
            usage.error = f"Failed to fetch rate limits: {error_msg}"
            logger.error(usage.error)
            return usage
        
        # Parse response
        usage.source = "cli-rpc"
        usage.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        result = limits_response.get("result", {})
        rate_limits = result.get("rateLimits", {})
        
        # Parse primary (5h limit)
        primary = rate_limits.get("primary", {})
        if primary:
            used_percent = primary.get("usedPercent", 0)
            usage.five_hour_percent_left = 100 - int(used_percent)
            
            resets_at = primary.get("resetsAt")
            if resets_at:
                reset_dt = datetime.fromtimestamp(resets_at)
                usage.five_hour_reset = reset_dt.strftime("%H:%M")
        
        # Parse secondary (weekly limit)
        secondary = rate_limits.get("secondary", {})
        if secondary:
            used_percent = secondary.get("usedPercent", 0)
            usage.weekly_percent_left = 100 - int(used_percent)
            
            resets_at = secondary.get("resetsAt")
            if resets_at:
                reset_dt = datetime.fromtimestamp(resets_at)
                usage.weekly_reset = reset_dt.strftime("%H:%M on %d %b")
        
        # Parse credits
        credits = rate_limits.get("credits", {})
        if credits:
            balance = credits.get("balance")
            if balance:
                usage.credits = f"Credits: {balance}"
            elif credits.get("unlimited"):
                usage.credits = "Credits: Unlimited"
        
        # Parse plan type
        plan_type = rate_limits.get("planType")
        if plan_type:
            usage.plan_type = plan_type.capitalize()
        
        logger.info(f"Codex usage fetched via RPC: 5h={usage.five_hour_percent_left}%, weekly={usage.weekly_percent_left}%")
        return usage
        
    except Exception as e:
        if process:
            try:
                process.terminate()
            except:
                pass
        usage.error = f"Error with codex RPC: {str(e)}"
        logger.exception("Exception in fetch_codex_status_cli")
        return usage


def fetch_codex_status_session() -> CodexUsage:
    """Fetch Codex usage from local session files (fallback)."""
    usage = CodexUsage()
    usage.source = "session"
    usage.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    logger.info("Fetching Codex usage from session files...")
    
    codex_home = Path.home() / ".codex"
    session_dirs = [
        codex_home / "sessions",
        codex_home / "archived_sessions"
    ]
    
    session_files = []
    for session_dir in session_dirs:
        if session_dir.exists():
            for jsonl_file in session_dir.rglob("*.jsonl"):
                session_files.append(jsonl_file)
    
    if not session_files:
        usage.error = "No Codex session files found"
        logger.warning(usage.error)
        return usage
    
    logger.debug(f"Found {len(session_files)} session files")
    
    # Sort by modification time (newest first)
    session_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    
    # Limit the number of files to check
    limit = config.get("codex", {}).get("session_file_limit", 10)
    
    for session_file in session_files[:limit]:
        try:
            with open(session_file, 'r') as f:
                for line in f:
                    try:
                        event = json.loads(line)
                        if (event.get("type") == "event_msg" and 
                            event.get("payload", {}).get("type") == "token_count"):
                            
                            rate_limits = event.get("payload", {}).get("rate_limits", {})
                            primary = rate_limits.get("primary", {})
                            secondary = rate_limits.get("secondary", {})
                            
                            if primary.get("window_minutes") or secondary.get("window_minutes"):
                                usage.five_hour_percent_left = 100 - int(primary.get("used_percent", 0))
                                usage.weekly_percent_left = 100 - int(secondary.get("used_percent", 0))
                                
                                if primary.get("resets_at"):
                                    reset_dt = datetime.fromtimestamp(primary["resets_at"])
                                    usage.five_hour_reset = reset_dt.strftime("%H:%M")
                                
                                if secondary.get("resets_at"):
                                    reset_dt = datetime.fromtimestamp(secondary["resets_at"])
                                    usage.weekly_reset = reset_dt.strftime("%H:%M on %d %b")
                                
                                plan_type = rate_limits.get("plan_type", "")
                                if plan_type:
                                    usage.plan_type = plan_type.capitalize()
                                
                                logger.info(f"Codex usage fetched from session: 5h={usage.five_hour_percent_left}%, weekly={usage.weekly_percent_left}%")
                                return usage
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.warning(f"Error reading session file {session_file}: {e}")
            continue
    
    usage.error = "No valid rate limit data found in session files"
    logger.warning(usage.error)
    return usage


def fetch_codex_usage() -> CodexUsage:
    """Fetch Codex usage based on configured source."""
    source = config.get("codex", {}).get("source", "auto")
    
    if source == "session":
        return fetch_codex_status_session()
    elif source == "cli":
        return fetch_codex_status_cli()
    else:  # auto
        # Try CLI first
        usage = fetch_codex_status_cli()
        if not usage.error and (usage.five_hour_percent_left >= 0 or usage.weekly_percent_left >= 0):
            return usage
        
        logger.info("CLI fetch failed, falling back to session files")
        return fetch_codex_status_session()


# ============================================================================
# Global Cache
# ============================================================================

usage_cache = CodexUsage()
cache_lock = threading.Lock()
last_fetch_time = 0
fetch_count = 0


def refresh_cache():
    """Refresh the usage cache."""
    global usage_cache, last_fetch_time, fetch_count
    
    while True:
        try:
            interval = config.get("refresh", {}).get("interval_seconds", 300)
            
            new_usage = fetch_codex_usage()
            with cache_lock:
                usage_cache = new_usage
                last_fetch_time = time.time()
                fetch_count += 1
            
            if new_usage.error:
                logger.warning(f"Cache refresh completed with error: {new_usage.error}")
            else:
                logger.info(f"Cache refreshed: 5h={new_usage.five_hour_percent_left}%, weekly={new_usage.weekly_percent_left}%")
        except Exception as e:
            logger.exception("Error in refresh_cache")
        
        time.sleep(interval)


# ============================================================================
# HTML Templates
# ============================================================================

def generate_main_html(usage: CodexUsage) -> str:
    """Generate main dashboard HTML."""
    error_section = ""
    if usage.error:
        error_section = f'''
    <div class="status-card">
        <h2>Warning</h2>
        <div class="error">{usage.error}</div>
    </div>'''
    
    five_hour_percent = usage.five_hour_percent_left if usage.five_hour_percent_left >= 0 else 0
    weekly_percent = usage.weekly_percent_left if usage.weekly_percent_left >= 0 else 0
    five_hour_reset = usage.five_hour_reset if usage.five_hour_reset else "Unknown"
    weekly_reset = usage.weekly_reset if usage.weekly_reset else "Unknown"
    plan_type = usage.plan_type if usage.plan_type else "Unknown"
    credits = usage.credits if usage.credits else "Unknown"
    source = usage.source if usage.source else "Unknown"
    last_updated = usage.last_updated if usage.last_updated else "Never"
    
    # Display settings
    display = config.get("display", {})
    
    account_info_rows = ""
    if display.get("show_plan_type", True):
        account_info_rows += f'''
        <div class="info-row">
            <span class="info-label">Plan:</span>
            <span class="info-value">{plan_type}</span>
        </div>'''
    
    if display.get("show_credits", True):
        account_info_rows += f'''
        <div class="info-row">
            <span class="info-label">Credits:</span>
            <span class="info-value">{credits}</span>
        </div>'''
    
    if display.get("show_data_source", True):
        account_info_rows += f'''
        <div class="info-row">
            <span class="info-label">Data Source:</span>
            <span class="info-value">{source}</span>
        </div>'''
    
    if display.get("show_last_updated", True):
        account_info_rows += f'''
        <div class="info-row">
            <span class="info-label">Last Updated:</span>
            <span class="info-value">{last_updated}</span>
        </div>'''
    
    refresh_ms = config.get("refresh", {}).get("auto_refresh_page_ms", 300000)
    
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Codex Usage Dashboard</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #ffffff;
            color: #000000;
            padding: 20px;
            max-width: 1080px;
            margin: 0 auto;
        }}
        
        .header {{
            text-align: center;
            margin-bottom: 30px;
            border-bottom: 2px solid #000000;
            padding-bottom: 15px;
            position: relative;
        }}
        
        .header h1 {{
            font-size: 2.5em;
            font-weight: bold;
            margin-bottom: 5px;
        }}
        
        .header .subtitle {{
            font-size: 1.2em;
            color: #333;
        }}
        
        .settings-btn {{
            position: absolute;
            top: 10px;
            right: 10px;
            background: #000000;
            color: #ffffff;
            border: none;
            padding: 10px 15px;
            font-size: 1em;
            cursor: pointer;
            border-radius: 5px;
            text-decoration: none;
        }}
        
        .settings-btn:hover {{
            background: #333333;
        }}
        
        .status-card {{
            border: 2px solid #000000;
            border-radius: 10px;
            padding: 25px;
            margin-bottom: 25px;
            background: #f8f8f8;
        }}
        
        .status-card h2 {{
            font-size: 1.8em;
            margin-bottom: 20px;
            border-bottom: 1px solid #ccc;
            padding-bottom: 10px;
        }}
        
        .limit-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding: 15px;
            background: #ffffff;
            border: 1px solid #ddd;
            border-radius: 5px;
        }}
        
        .limit-label {{
            font-size: 1.4em;
            font-weight: bold;
            min-width: 150px;
        }}
        
        .limit-bar {{
            flex: 1;
            margin: 0 20px;
            height: 40px;
            background: #e0e0e0;
            border-radius: 5px;
            overflow: hidden;
            position: relative;
        }}
        
        .limit-bar-fill {{
            height: 100%;
            background: #000000;
            transition: width 0.3s ease;
        }}
        
        .limit-percent {{
            font-size: 1.6em;
            font-weight: bold;
            min-width: 80px;
            text-align: right;
        }}
        
        .limit-reset {{
            font-size: 1em;
            color: #666;
            margin-top: 5px;
        }}
        
        .info-row {{
            display: flex;
            justify-content: space-between;
            padding: 10px 0;
            border-bottom: 1px solid #eee;
        }}
        
        .info-label {{
            font-weight: bold;
            font-size: 1.2em;
        }}
        
        .info-value {{
            font-size: 1.2em;
        }}
        
        .error {{
            color: #cc0000;
            font-style: italic;
            padding: 10px;
            background: #fff0f0;
            border: 1px solid #ffcccc;
            border-radius: 5px;
        }}
        
        .footer {{
            text-align: center;
            margin-top: 30px;
            padding-top: 15px;
            border-top: 2px solid #000000;
            color: #666;
        }}
        
        .auto-refresh {{
            font-size: 1em;
            color: #888;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Codex Usage</h1>
        <div class="subtitle">Kindle Dashboard</div>
        <a href="/settings" class="settings-btn">Settings</a>
    </div>
    
    <div class="status-card">
        <h2>Rate Limits</h2>
        
        <div class="limit-row">
            <div>
                <div class="limit-label">5 Hour Limit</div>
                <div class="limit-reset">Resets: {five_hour_reset}</div>
            </div>
            <div class="limit-bar">
                <div class="limit-bar-fill" style="width: {five_hour_percent}%"></div>
            </div>
            <div class="limit-percent">{five_hour_percent}% left</div>
        </div>
        
        <div class="limit-row">
            <div>
                <div class="limit-label">Weekly Limit</div>
                <div class="limit-reset">Resets: {weekly_reset}</div>
            </div>
            <div class="limit-bar">
                <div class="limit-bar-fill" style="width: {weekly_percent}%"></div>
            </div>
            <div class="limit-percent">{weekly_percent}% left</div>
        </div>
    </div>
    
    <div class="status-card">
        <h2>Account Info</h2>
        {account_info_rows}
    </div>
    
    {error_section}
    
    <div class="footer">
        <div class="auto-refresh">Auto-refreshes every {refresh_ms // 1000} seconds</div>
        <div>KindleVibe-Python</div>
    </div>
    
    <script>
        setTimeout(function() {{
            location.reload();
        }}, {refresh_ms});
    </script>
</body>
</html>'''
    
    return html


def generate_settings_html(message: str = "", message_type: str = "") -> str:
    """Generate settings page HTML."""
    msg_html = ""
    if message:
        msg_class = "success" if message_type == "success" else "error"
        msg_html = f'<div class="{msg_class}">{message}</div>'
    
    # Server settings
    server_port = config.get("server", {}).get("port", 8080)
    server_host = config.get("server", {}).get("host", "0.0.0.0")
    
    # Refresh settings
    refresh_interval = config.get("refresh", {}).get("interval_seconds", 300)
    refresh_page = config.get("refresh", {}).get("auto_refresh_page_ms", 300000) // 1000
    
    # Codex settings
    codex_enabled = config.get("codex", {}).get("enabled", True)
    codex_source = config.get("codex", {}).get("source", "auto")
    session_limit = config.get("codex", {}).get("session_file_limit", 10)
    
    # Display settings
    display = config.get("display", {})
    show_credits = display.get("show_credits", True)
    show_plan = display.get("show_plan_type", True)
    show_source = display.get("show_data_source", True)
    show_updated = display.get("show_last_updated", True)
    
    def checked(val):
        return "checked" if val else ""
    
    def selected(val, target):
        return "selected" if val == target else ""
    
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Settings - KindleVibe</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #ffffff;
            color: #000000;
            padding: 20px;
            max-width: 800px;
            margin: 0 auto;
        }}
        
        .header {{
            text-align: center;
            margin-bottom: 30px;
            border-bottom: 2px solid #000000;
            padding-bottom: 15px;
            position: relative;
        }}
        
        .header h1 {{
            font-size: 2em;
            font-weight: bold;
        }}
        
        .back-btn {{
            position: absolute;
            top: 10px;
            left: 10px;
            background: #000000;
            color: #ffffff;
            border: none;
            padding: 10px 15px;
            font-size: 1em;
            cursor: pointer;
            border-radius: 5px;
            text-decoration: none;
        }}
        
        .back-btn:hover {{
            background: #333333;
        }}
        
        .settings-section {{
            border: 2px solid #000000;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 20px;
            background: #f8f8f8;
        }}
        
        .settings-section h2 {{
            font-size: 1.4em;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 1px solid #ccc;
        }}
        
        .form-group {{
            margin-bottom: 15px;
        }}
        
        .form-group label {{
            display: block;
            font-weight: bold;
            margin-bottom: 5px;
            font-size: 1.1em;
        }}
        
        .form-group input[type="number"],
        .form-group input[type="text"],
        .form-group select {{
            width: 100%;
            padding: 10px;
            font-size: 1em;
            border: 1px solid #ddd;
            border-radius: 5px;
            background: #ffffff;
        }}
        
        .form-group .checkbox-label {{
            display: flex;
            align-items: center;
            gap: 10px;
            font-weight: normal;
            cursor: pointer;
        }}
        
        .form-group input[type="checkbox"] {{
            width: 20px;
            height: 20px;
            cursor: pointer;
        }}
        
        .form-actions {{
            text-align: center;
            margin-top: 20px;
        }}
        
        .btn {{
            background: #000000;
            color: #ffffff;
            border: none;
            padding: 12px 30px;
            font-size: 1.1em;
            cursor: pointer;
            border-radius: 5px;
            margin: 0 10px;
        }}
        
        .btn:hover {{
            background: #333333;
        }}
        
        .btn-secondary {{
            background: #666666;
        }}
        
        .btn-secondary:hover {{
            background: #888888;
        }}
        
        .success {{
            color: #006600;
            background: #e6ffe6;
            border: 1px solid #00cc00;
            padding: 10px;
            border-radius: 5px;
            margin-bottom: 15px;
            text-align: center;
        }}
        
        .error {{
            color: #cc0000;
            background: #fff0f0;
            border: 1px solid #ffcccc;
            padding: 10px;
            border-radius: 5px;
            margin-bottom: 15px;
            text-align: center;
        }}
        
        .help-text {{
            font-size: 0.9em;
            color: #666;
            margin-top: 5px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <a href="/" class="back-btn">Back</a>
        <h1>Settings</h1>
    </div>
    
    {msg_html}
    
    <form method="POST" action="/settings">
        <div class="settings-section">
            <h2>Server Settings</h2>
            
            <div class="form-group">
                <label for="port">Port:</label>
                <input type="number" id="port" name="port" value="{server_port}" min="1" max="65535">
                <div class="help-text">Server listening port (requires restart)</div>
            </div>
            
            <div class="form-group">
                <label for="host">Host:</label>
                <input type="text" id="host" name="host" value="{server_host}">
                <div class="help-text">Server bind address (use 0.0.0.0 for all interfaces)</div>
            </div>
        </div>
        
        <div class="settings-section">
            <h2>Refresh Settings</h2>
            
            <div class="form-group">
                <label for="refresh_interval">Data Refresh Interval (seconds):</label>
                <input type="number" id="refresh_interval" name="refresh_interval" value="{refresh_interval}" min="30" max="3600">
                <div class="help-text">How often to fetch new data from Codex (30-3600 seconds)</div>
            </div>
            
            <div class="form-group">
                <label for="refresh_page">Page Auto-Refresh (seconds):</label>
                <input type="number" id="refresh_page" name="refresh_page" value="{refresh_page}" min="30" max="3600">
                <div class="help-text">How often the browser page auto-refreshes</div>
            </div>
        </div>
        
        <div class="settings-section">
            <h2>Codex Settings</h2>
            
            <div class="form-group">
                <label class="checkbox-label">
                    <input type="checkbox" name="codex_enabled" {"checked" if codex_enabled else ""}>
                    Enable Codex monitoring
                </label>
            </div>
            
            <div class="form-group">
                <label for="codex_source">Data Source:</label>
                <select id="codex_source" name="codex_source">
                    <option value="auto" {selected(codex_source, "auto")}>Auto (CLI first, then session files)</option>
                    <option value="cli" {selected(codex_source, "cli")}>CLI RPC only</option>
                    <option value="session" {selected(codex_source, "session")}>Session files only</option>
                </select>
                <div class="help-text">Where to fetch Codex usage data</div>
            </div>
            
            <div class="form-group">
                <label for="session_limit">Session File Limit:</label>
                <input type="number" id="session_limit" name="session_limit" value="{session_limit}" min="1" max="100">
                <div class="help-text">Max number of session files to scan (1-100)</div>
            </div>
        </div>
        
        <div class="settings-section">
            <h2>Display Settings</h2>
            
            <div class="form-group">
                <label class="checkbox-label">
                    <input type="checkbox" name="show_plan_type" {"checked" if show_plan else ""}>
                    Show Plan Type
                </label>
            </div>
            
            <div class="form-group">
                <label class="checkbox-label">
                    <input type="checkbox" name="show_credits" {"checked" if show_credits else ""}>
                    Show Credits
                </label>
            </div>
            
            <div class="form-group">
                <label class="checkbox-label">
                    <input type="checkbox" name="show_data_source" {"checked" if show_source else ""}>
                    Show Data Source
                </label>
            </div>
            
            <div class="form-group">
                <label class="checkbox-label">
                    <input type="checkbox" name="show_last_updated" {"checked" if show_updated else ""}>
                    Show Last Updated
                </label>
            </div>
        </div>
        
        <div class="form-actions">
            <button type="submit" class="btn">Save Settings</button>
            <a href="/" class="btn btn-secondary">Cancel</a>
        </div>
    </form>
</body>
</html>'''
    
    return html


# ============================================================================
# HTTP Request Handler
# ============================================================================

class RequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler."""
    
    def do_GET(self):
        parsed_path = urlparse(self.path)
        path = parsed_path.path
        
        if path == "/" or path == "/index.html":
            with cache_lock:
                usage = usage_cache
            
            html = generate_main_html(usage)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
        
        elif path == "/settings":
            html = generate_settings_html()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
        
        elif path == "/api/usage":
            with cache_lock:
                usage = usage_cache
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(usage.to_dict(), indent=2).encode("utf-8"))
        
        elif path == "/api/config":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(config, indent=2).encode("utf-8"))
        
        else:
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<h1>404 Not Found</h1>")
    
    def do_POST(self):
        if self.path == "/settings":
            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length).decode("utf-8")
            params = parse_qs(post_data)
            
            try:
                # Update server settings
                if "port" in params:
                    config["server"]["port"] = int(params["port"][0])
                if "host" in params:
                    config["server"]["host"] = params["host"][0]
                
                # Update refresh settings
                if "refresh_interval" in params:
                    interval = int(params["refresh_interval"][0])
                    config["refresh"]["interval_seconds"] = max(30, min(3600, interval))
                if "refresh_page" in params:
                    page_refresh = int(params["refresh_page"][0])
                    config["refresh"]["auto_refresh_page_ms"] = max(30, min(3600, page_refresh)) * 1000
                
                # Update codex settings
                config["codex"]["enabled"] = "codex_enabled" in params
                if "codex_source" in params:
                    config["codex"]["source"] = params["codex_source"][0]
                if "session_limit" in params:
                    limit = int(params["session_limit"][0])
                    config["codex"]["session_file_limit"] = max(1, min(100, limit))
                
                # Update display settings
                config["display"]["show_plan_type"] = "show_plan_type" in params
                config["display"]["show_credits"] = "show_credits" in params
                config["display"]["show_data_source"] = "show_data_source" in params
                config["display"]["show_last_updated"] = "show_last_updated" in params
                
                # Save config
                if save_config(config):
                    logger.info("Settings saved successfully")
                    html = generate_settings_html("Settings saved successfully!", "success")
                else:
                    html = generate_settings_html("Failed to save settings!", "error")
                
            except Exception as e:
                logger.exception("Error saving settings")
                html = generate_settings_html(f"Error: {str(e)}", "error")
            
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
        
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        """Override to use our logger."""
        logger.debug(f"HTTP {args[0]}")


# ============================================================================
# Main Entry Point
# ============================================================================

def get_local_ip() -> str:
    """Get the local IP address of this machine (excluding VPN)."""
    import socket
    import subprocess
    
    # VPN interfaces to skip
    vpn_prefixes = ('utun', 'tun', 'tap', 'ppp', 'ipsec', 'wg')
    
    try:
        # Method 1: Try to get IP from network interfaces using ifconfig
        result = subprocess.run(
            ['ifconfig'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            current_interface = None
            for line in result.stdout.split('\n'):
                # Detect interface name
                if not line.startswith(' ') and ':' in line:
                    current_interface = line.split(':')[0].strip()
                
                # Look for inet address
                if 'inet ' in line and current_interface:
                    # Skip VPN interfaces
                    if current_interface.startswith(vpn_prefixes):
                        continue
                    
                    # Skip loopback
                    if '127.0.0.1' in line:
                        continue
                    
                    # Extract IP
                    parts = line.strip().split()
                    for i, part in enumerate(parts):
                        if part == 'inet' and i + 1 < len(parts):
                            ip = parts[i + 1]
                            # Verify it's a valid local IP
                            if ip.startswith(('192.168.', '10.', '172.16.', '172.17.', '172.18.', '172.19.', '172.20.', '172.21.', '172.22.', '172.23.', '172.24.', '172.25.', '172.26.', '172.27.', '172.28.', '172.29.', '172.30.', '172.31.')):
                                return ip
        
        # Method 2: Fallback to socket method
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return '127.0.0.1'


def main():
    """Main entry point."""
    global config
    
    # Reload config in case it was modified
    config = load_config()
    
    server_port = config.get("server", {}).get("port", 8080)
    server_host = config.get("server", {}).get("host", "0.0.0.0")
    
    # Get local IP
    local_ip = get_local_ip()
    
    # Start background refresh thread
    refresh_thread = threading.Thread(target=refresh_cache, daemon=True)
    refresh_thread.start()
    logger.info("Background refresh thread started")
    
    # Initial fetch
    logger.info("Fetching initial Codex usage data...")
    global usage_cache
    usage_cache = fetch_codex_usage()
    logger.info(f"Initial fetch complete: 5h={usage_cache.five_hour_percent_left}%, weekly={usage_cache.weekly_percent_left}%")
    
    # Start HTTP server
    server = HTTPServer((server_host, server_port), RequestHandler)
    
    # Print connection info
    print("\n" + "=" * 50)
    print("  KindleVibe-Python Started!")
    print("=" * 50)
    print(f"\n  Local access:  http://localhost:{server_port}")
    print(f"  Network access: http://{local_ip}:{server_port}")
    print(f"\n  Use the Network address on your Kindle")
    print("=" * 50 + "\n")
    
    logger.info(f"Starting KindleVibe-Python on http://{local_ip}:{server_port}")
    logger.info("Press Ctrl+C to stop")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        logger.info("Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
