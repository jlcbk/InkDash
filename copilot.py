import json
import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

import urllib.request
import urllib.error

from config import config

logger = logging.getLogger("KindleVibe.Copilot")


class CopilotUsage:
    def __init__(self):
        self.plan: str = ""
        self.premium_percent: int = -1
        self.chat_percent: int = -1
        self.reset: str = ""
        self.last_updated: str = ""
        self.error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan": self.plan,
            "premium_percent": self.premium_percent,
            "chat_percent": self.chat_percent,
            "reset": self.reset,
            "last_updated": self.last_updated,
            "error": self.error,
        }


def resolve_copilot_token() -> Optional[str]:
    cfg_token = config.get("copilot", "token", default="")
    if cfg_token:
        return cfg_token

    env_token = os.environ.get("COPILOT_API_TOKEN", "").strip()
    if env_token:
        return env_token

    apps_path = Path.home() / ".config" / "github-copilot" / "apps.json"
    if not apps_path.exists():
        return None

    try:
        with open(apps_path) as f:
            apps = json.load(f)
        if isinstance(apps, dict):
            for key in sorted(apps.keys()):
                token = apps[key].get("oauth_token", "").strip()
                if token:
                    return token
    except Exception as e:
        logger.warning(f"Error reading {apps_path}: {e}")

    return None


def fetch_copilot_usage() -> CopilotUsage:
    usage = CopilotUsage()
    token = resolve_copilot_token()
    if not token:
        usage.error = "No Copilot token found. Set copilot.token in config, COPILOT_API_TOKEN, or sign in via GitHub Copilot."
        return usage

    try:
        req = urllib.request.Request("https://api.github.com/copilot_internal/user")
        req.add_header("Authorization", f"token {token}")
        req.add_header("Accept", "application/json")
        req.add_header("Editor-Version", "vscode/1.96.2")
        req.add_header("Editor-Plugin-Version", "copilot-chat/0.26.7")
        req.add_header("User-Agent", "GitHubCopilotChat/0.26.7")
        req.add_header("X-Github-Api-Version", "2025-04-01")

        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())

        usage.last_updated = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        plan = body.get("copilot_plan", "")
        if plan:
            usage.plan = plan.replace("-", " ").replace("_", " ").title()

        snapshots = body.get("quota_snapshots", {})
        if not snapshots:
            usage.error = "No quota snapshots found in Copilot response"
            return usage

        def select_snapshot(*names):
            for name in names:
                for key, snap in snapshots.items():
                    if key.lower() == name.lower() or snap.get("quota_id", "").lower() == name.lower():
                        return snap
            return None

        def used_percent(snap) -> Optional[int]:
            if "percent_remaining" in snap and snap["percent_remaining"] is not None:
                return max(0, min(100, 100 - int(float(snap["percent_remaining"]))))
            entitlement = snap.get("entitlement")
            remaining = snap.get("remaining")
            if entitlement and remaining and float(entitlement) > 0:
                return max(0, min(100, int(100 - (float(remaining) / float(entitlement) * 100))))
            return None

        premium = select_snapshot("premium_interactions", "premium", "completions", "code")
        if premium:
            pct = used_percent(premium)
            if pct is not None:
                usage.premium_percent = pct

        chat = select_snapshot("chat")
        if chat:
            pct = used_percent(chat)
            if pct is not None:
                usage.chat_percent = pct

        for field in ["quota_reset_date_utc", "quota_reset_date"]:
            val = body.get(field, "")
            if val:
                usage.reset = val
                break
        if not usage.reset:
            usage.reset = "Unknown"

        if usage.premium_percent < 0 and usage.chat_percent < 0:
            usage.error = "No usable Copilot quota snapshots found"

        logger.info(f"Copilot: plan={usage.plan}, premium={usage.premium_percent}%, chat={usage.chat_percent}%")
        return usage

    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            usage.error = "Copilot token is invalid or expired"
        else:
            usage.error = f"Copilot HTTP {e.code}: {e.reason}"
        return usage
    except Exception as e:
        usage.error = f"Copilot error: {e}"
        logger.exception("Copilot fetch failed")
        return usage
