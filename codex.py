import json
import logging
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from config import config

logger = logging.getLogger("KindleVibe.Codex")


class CodexUsage:
    def __init__(self):
        self.five_hour_percent_left: int = -1
        self.five_hour_reset: str = ""
        self.weekly_percent_left: int = -1
        self.weekly_reset: str = ""
        self.credits: str = ""
        self.plan_type: str = ""
        self.last_updated: str = ""
        self.source: str = ""
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
    try:
        result = subprocess.run(["which", "codex"], capture_output=True, text=True)
        if result.returncode == 0:
            path = result.stdout.strip()
            logger.debug(f"Found codex at: {path}")
            return path
    except Exception as e:
        logger.warning(f"Error finding codex: {e}")
    return None


def fetch_codex_status_cli() -> CodexUsage:
    usage = CodexUsage()
    codex_path = find_codex_binary()
    if not codex_path:
        usage.error = "codex not found in PATH"
        return usage

    process = None
    try:
        logger.info("Starting codex app-server for RPC...")
        process = subprocess.Popen(
            [codex_path, "-s", "read-only", "-a", "untrusted", "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        stdout_lines = []
        stdout_lock = threading.Lock()

        def read_stdout():
            for line in iter(process.stdout.readline, b''):
                with stdout_lock:
                    stdout_lines.append(line)

        reader_thread = threading.Thread(target=read_stdout, daemon=True)
        reader_thread.start()

        request_counter = [0]

        def send_request(method: str, params: Optional[Dict] = None, timeout: float = 3.0) -> Optional[Dict]:
            request_counter[0] += 1
            request_id = request_counter[0]
            request = {"id": request_id, "method": method, "params": params or {}}
            process.stdin.write(json.dumps(request).encode() + b"\n")
            process.stdin.flush()
            start = time.time()
            while time.time() - start < timeout:
                with stdout_lock:
                    for line in stdout_lines:
                        try:
                            msg = json.loads(line.decode().strip())
                            if msg.get("id") == request_id:
                                return msg
                        except json.JSONDecodeError:
                            continue
                time.sleep(0.1)
            return None

        def send_notification(method: str, params: Optional[Dict] = None):
            notification = {"method": method, "params": params or {}}
            process.stdin.write(json.dumps(notification).encode() + b"\n")
            process.stdin.flush()

        init_response = send_request("initialize", {
            "clientInfo": {"name": "kindlevibe", "version": "1.0.0"}
        }, timeout=5.0)

        if not init_response or "error" in init_response:
            err = (init_response.get("error", {}).get("message", "No response")
                   if init_response else "No response")
            usage.error = f"Initialize failed: {err}"
            process.terminate()
            return usage

        send_notification("initialized")
        limits_response = send_request("account/rateLimits/read", timeout=5.0)
        process.terminate()

        if not limits_response or "error" in limits_response:
            err = (limits_response.get("error", {}).get("message", "Unknown error")
                   if limits_response else "No response")
            usage.error = f"Rate limits failed: {err}"
            return usage

        usage.source = "cli-rpc"
        usage.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        result = limits_response.get("result", {})
        rate_limits = result.get("rateLimits", {})

        primary = rate_limits.get("primary", {})
        if primary:
            usage.five_hour_percent_left = 100 - int(primary.get("usedPercent", 0))
            resets_at = primary.get("resetsAt")
            if resets_at:
                usage.five_hour_reset = datetime.fromtimestamp(resets_at).strftime("%H:%M")

        secondary = rate_limits.get("secondary", {})
        if secondary:
            usage.weekly_percent_left = 100 - int(secondary.get("usedPercent", 0))
            resets_at = secondary.get("resetsAt")
            if resets_at:
                usage.weekly_reset = datetime.fromtimestamp(resets_at).strftime("%H:%M on %d %b")

        credits = rate_limits.get("credits", {})
        if credits:
            balance = credits.get("balance")
            if balance:
                usage.credits = f"Credits: {balance}"
            elif credits.get("unlimited"):
                usage.credits = "Credits: Unlimited"

        plan_type = rate_limits.get("planType")
        if plan_type:
            usage.plan_type = plan_type.capitalize()

        logger.info(f"Codex RPC: 5h={usage.five_hour_percent_left}%, weekly={usage.weekly_percent_left}%")
        return usage

    except Exception as e:
        if process:
            try:
                process.terminate()
            except Exception:
                pass
        usage.error = f"RPC error: {e}"
        logger.exception("Codex RPC failed")
        return usage


def fetch_codex_status_session() -> CodexUsage:
    usage = CodexUsage()
    usage.source = "session"
    usage.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    codex_home = Path.home() / ".codex"
    session_dirs = [codex_home / "sessions", codex_home / "archived_sessions"]
    session_files = []
    for sd in session_dirs:
        if sd.exists():
            session_files.extend(sd.rglob("*.jsonl"))

    if not session_files:
        usage.error = "No Codex session files found"
        return usage

    session_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    limit = config.get("codex", "session_file_limit", default=10)

    for sf in session_files[:limit]:
        try:
            with open(sf) as f:
                for line in f:
                    try:
                        event = json.loads(line)
                        if not isinstance(event, dict) or event.get("type") != "event_msg":
                            continue
                        payload = event.get("payload")
                        if not isinstance(payload, dict) or payload.get("type") != "token_count":
                            continue

                        rl = payload.get("rate_limits")
                        if not isinstance(rl, dict):
                            continue
                        primary = rl.get("primary", {})
                        secondary = rl.get("secondary", {})
                        if primary.get("window_minutes") or secondary.get("window_minutes"):
                            usage.five_hour_percent_left = 100 - int(primary.get("used_percent", 0))
                            usage.weekly_percent_left = 100 - int(secondary.get("used_percent", 0))
                            if primary.get("resets_at"):
                                usage.five_hour_reset = datetime.fromtimestamp(primary["resets_at"]).strftime("%H:%M")
                            if secondary.get("resets_at"):
                                usage.weekly_reset = datetime.fromtimestamp(secondary["resets_at"]).strftime("%H:%M on %d %b")
                            pt = rl.get("plan_type", "")
                            if pt:
                                usage.plan_type = pt.capitalize()
                            logger.info(f"Codex session: 5h={usage.five_hour_percent_left}%, weekly={usage.weekly_percent_left}%")
                            return usage
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.warning(f"Error reading {sf}: {e}")
            continue

    usage.error = "No valid rate limit data in session files"
    return usage


def fetch_codex_usage() -> CodexUsage:
    source = config.get("codex", "source", default="auto")
    if source == "session":
        return fetch_codex_status_session()
    elif source == "cli":
        return fetch_codex_status_cli()
    usage = fetch_codex_status_cli()
    if not usage.error and (usage.five_hour_percent_left >= 0 or usage.weekly_percent_left >= 0):
        return usage
    logger.info("Falling back to session files")
    return fetch_codex_status_session()
