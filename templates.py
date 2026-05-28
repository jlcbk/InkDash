import math
from datetime import datetime
from typing import Dict, Any, Optional

from config import config
from codex import CodexUsage
from copilot import CopilotUsage


def clamp_percent(value: float) -> int:
    return max(0, min(100, int(round(value))))


def meter_fill(percentage: int, total: int = 10):
    filled = int(round((clamp_percent(float(percentage)) / 100) * total))
    return [(i < filled) for i in range(total)]


def compact_reset_text(value: str) -> str:
    if not value or value == "Unknown":
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00").split(".")[0])
        if dt.date() == datetime.now().date():
            return dt.strftime("%H:%M")
        return dt.strftime("%m-%d %H:%M")
    except (ValueError, TypeError):
        return value


def provider_meta(reset: str) -> str:
    text = compact_reset_text(reset)
    return f"↻ {text}" if text else ""


def segments_html(filled_count: int, total: int = 10) -> str:
    segs = []
    for i in range(total):
        cls = "segment filled" if i < filled_count else "segment"
        segs.append(f'<div class="{cls}"></div>')
    return "".join(segs)


def generate_main_html(codex_usage: CodexUsage, copilot_usage: Optional[CopilotUsage] = None) -> str:
    refresh_ms = config.get("refresh", "page_refresh_ms", default=300000)

    provider_panels = []

    # Codex panel
    codex_bars = []
    if codex_usage.five_hour_percent_left >= 0:
        codex_bars.append({
            "label": "5H LIMIT",
            "percent": codex_usage.five_hour_percent_left,
            "meta": provider_meta(codex_usage.five_hour_reset),
        })
    if codex_usage.weekly_percent_left >= 0:
        codex_bars.append({
            "label": "WEEKLY LIMIT",
            "percent": codex_usage.weekly_percent_left,
            "meta": provider_meta(codex_usage.weekly_reset),
        })
    codex_detail_parts = []
    if codex_usage.plan_type:
        codex_detail_parts.append(codex_usage.plan_type.upper())
    if codex_usage.credits:
        codex_detail_parts.append(codex_usage.credits.upper())
    codex_detail = " | ".join(codex_detail_parts)

    provider_panels.append({
        "name": "CODEX",
        "detail": codex_detail,
        "bars": codex_bars,
        "has_data": len(codex_bars) > 0,
    })

    # Copilot panel
    if copilot_usage:
        copilot_bars = []
        if copilot_usage.premium_percent >= 0:
            copilot_bars.append({
                "label": "PREMIUM",
                "percent": copilot_usage.premium_percent,
                "meta": provider_meta(copilot_usage.reset),
            })
        if copilot_usage.chat_percent >= 0:
            copilot_bars.append({
                "label": "CHAT",
                "percent": copilot_usage.chat_percent,
                "meta": provider_meta(copilot_usage.reset),
            })
        provider_panels.append({
            "name": "COPILOT",
            "detail": copilot_usage.plan.upper() if copilot_usage.plan else "",
            "bars": copilot_bars,
            "has_data": len(copilot_bars) > 0,
        })

    panels_html = ""
    for panel in provider_panels:
        detail_row = f'<div class="provider-detail">{panel["detail"]}</div>' if panel["detail"] else ""
        bars_html = ""
        if not panel["has_data"]:
            segs = segments_html(0)
            bars_html = f'''<div class="bar-row">
              <div class="bar-label">STATUS</div>
              <div class="bar-layout">
                <div class="bar-track">{segs}</div>
                <div class="bar-value"><span class="bar-value-text">--</span></div>
              </div>
              <div class="bar-meta">DATA UNAVAILABLE</div>
            </div>'''
        else:
            for b in panel["bars"]:
                segs = segments_html(b["percent"])
                meta_row = f'<div class="bar-meta">{b["meta"]}</div>' if b["meta"] else ""
                bars_html += f'''<div class="bar-row">
              <div class="bar-label">{b["label"]}</div>
              <div class="bar-layout">
                <div class="bar-track">{segs}</div>
                <div class="bar-value"><span class="bar-value-text">{b["percent"]}%</span></div>
              </div>
              {meta_row}
            </div>'''

        panels_html += f'''<div class="provider">
        <div class="provider-name">{panel["name"]}</div>
        {detail_row}
        {bars_html}
      </div>'''

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>KindleVibe</title>
<style>
html, body {{ margin:0; padding:0; background:#fff; color:#000; }}
body {{ font-family:"Bookerly","Palatino","Georgia",serif; padding:50px 14px 24px; max-width:760px; margin:0 auto; }}
.frame {{ width:auto; }}
.header {{ text-align:center; border-bottom:2px solid #000; padding-bottom:10px; margin-bottom:20px; }}
.header h1 {{ font-size:26px; font-weight:bold; margin:0 0 4px; }}
.header .subtitle {{ font-size:15px; color:#888; margin:0; }}
.top-nav {{ position:fixed; left:0; right:0; top:0; z-index:900; height:42px; background:#fff; border-bottom:3px solid #ccc; }}
.tab-bar {{ position:absolute; left:50%; top:8px; transform:translateX(-50%); display:flex; align-items:center; gap:0; }}
.tab-link {{ display:block; color:#888; text-decoration:none; font-size:13px; font-weight:bold; letter-spacing:0.1em; text-transform:uppercase; padding:4px 10px; background:transparent; }}
.tab-link.active {{ color:#000; text-decoration:underline; text-underline-offset:3px; }}
.tab-divider {{ width:1px; height:14px; background:#ccc; flex-shrink:0; }}
.provider {{ border:3px solid #ccc; padding:3px 10px; margin-bottom:10px; }}
.provider-name {{ font-size:22px; font-weight:bold; margin:4px 0 8px; }}
.provider-detail {{ color:#ccc; font-size:16px; font-weight:bold; line-height:30px; margin-top:8px; }}
.bar-row {{ margin-bottom:10px; }}
.bar-label {{ color:#666; font-size:14px; margin-bottom:3px; }}
.bar-layout {{ display:flex; align-items:center; }}
.bar-track {{ flex:1; display:flex; gap:2px; min-width:0; }}
.segment {{ flex:1; height:18px; background:#d6d2cc; }}
.segment.filled {{ background:#000; }}
.bar-value {{ flex-shrink:0; margin-left:8px; }}
.bar-value-text {{ font-size:22px; line-height:28px; font-weight:bold; }}
.bar-meta {{ color:#6d6965; font-size:12px; line-height:14px; min-height:14px; }}
.error {{ color:#c00; font-style:italic; padding:10px; background:#fff0f0; border:1px solid #fcc; border-radius:5px; margin-bottom:15px; }}
.footer {{ text-align:center; margin-top:20px; padding-top:10px; border-top:2px solid #000; color:#666; font-size:13px; }}
.auto-refresh {{ color:#888; font-size:12px; margin-bottom:4px; }}
.time {{ color:#aaa; font-size:11px; }}
</style>
</head>
<body>
<div class="top-nav"><div class="tab-bar"><span class="tab-link active">Dashboard</span></div></div>
<div class="frame">
<div class="header">
  <h1>KindleVibe</h1>
  <div class="subtitle">Codex · Copilot</div>
</div>
<div class="provider-row">
  {panels_html}
</div>
<div class="footer">
  <div class="auto-refresh">Auto-refreshes every {refresh_ms // 1000}s</div>
  <div class="time">{datetime.now().strftime("%Y-%m-%d %H:%M")}</div>
</div>
</div>
<script>
setTimeout(function(){{location.reload()}},{refresh_ms});
</script>
</body>
</html>'''


def generate_settings_html(message: str = "", message_type: str = "") -> str:
    msg_html = ""
    if message:
        cls = "success" if message_type == "success" else "error"
        msg_html = f'<div class="{cls}">{message}</div>'

    port = config.get("server", "port", default=8080)
    host = config.get("server", "host", default="0.0.0.0")
    refresh_interval = config.get("refresh", "interval_seconds", default=300)
    page_refresh = config.get("refresh", "page_refresh_ms", default=300000) // 1000
    codex_enabled = config.get("codex", "enabled", default=True)
    codex_source = config.get("codex", "source", default="auto")
    session_limit = config.get("codex", "session_file_limit", default=10)
    copilot_enabled = config.get("copilot", "enabled", default=True)
    copilot_token = config.get("copilot", "token", default="")

    def checked(val):
        return "checked" if val else ""

    def selected(val, target):
        return "selected" if val == target else ""

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Settings - KindleVibe</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; background:#fff; color:#000; padding:20px; max-width:800px; margin:0 auto; }}
.header {{ text-align:center; margin-bottom:30px; border-bottom:2px solid #000; padding-bottom:15px; position:relative; }}
.header h1 {{ font-size:2em; font-weight:bold; }}
.back-btn {{ position:absolute; top:10px; left:10px; background:#000; color:#fff; border:none; padding:10px 15px; font-size:1em; cursor:pointer; border-radius:5px; text-decoration:none; }}
.settings-section {{ border:2px solid #000; border-radius:10px; padding:20px; margin-bottom:20px; background:#f8f8f8; }}
.settings-section h2 {{ font-size:1.4em; margin-bottom:15px; padding-bottom:10px; border-bottom:1px solid #ccc; }}
.form-group {{ margin-bottom:15px; }}
.form-group label {{ display:block; font-weight:bold; margin-bottom:5px; font-size:1.1em; }}
.form-group input[type="number"], .form-group input[type="text"], .form-group select {{ width:100%; padding:10px; font-size:1em; border:1px solid #ddd; border-radius:5px; }}
.form-group .checkbox-label {{ display:flex; align-items:center; gap:10px; font-weight:normal; cursor:pointer; }}
.form-group input[type="checkbox"] {{ width:20px; height:20px; cursor:pointer; }}
.form-actions {{ text-align:center; margin-top:20px; }}
.btn {{ background:#000; color:#fff; border:none; padding:12px 30px; font-size:1.1em; cursor:pointer; border-radius:5px; margin:0 10px; display:inline-block; text-decoration:none; }}
.btn-secondary {{ background:#666; }}
.success {{ color:#060; background:#e6ffe6; border:1px solid #0c0; padding:10px; border-radius:5px; margin-bottom:15px; text-align:center; }}
.error {{ color:#c00; background:#fff0f0; border:1px solid #fcc; padding:10px; border-radius:5px; margin-bottom:15px; text-align:center; }}
.help-text {{ font-size:0.9em; color:#666; margin-top:5px; }}
</style>
</head>
<body>
<div class="header"><a href="/" class="back-btn">Back</a><h1>Settings</h1></div>
{msg_html}
<form method="POST" action="/settings">
<div class="settings-section">
<h2>Server Settings</h2>
<div class="form-group"><label for="port">Port:</label><input type="number" id="port" name="port" value="{port}" min="1" max="65535"><div class="help-text">Requires restart</div></div>
<div class="form-group"><label for="host">Host:</label><input type="text" id="host" name="host" value="{host}"><div class="help-text">0.0.0.0 for all interfaces</div></div>
</div>
<div class="settings-section">
<h2>Refresh Settings</h2>
<div class="form-group"><label for="refresh_interval">Data Refresh (seconds):</label><input type="number" id="refresh_interval" name="refresh_interval" value="{refresh_interval}" min="30" max="3600"></div>
<div class="form-group"><label for="page_refresh">Page Refresh (seconds):</label><input type="number" id="page_refresh" name="page_refresh" value="{page_refresh}" min="30" max="3600"></div>
</div>
<div class="settings-section">
<h2>Codex Settings</h2>
<div class="form-group"><label class="checkbox-label"><input type="checkbox" name="codex_enabled" {checked(codex_enabled)}>Enable Codex</label></div>
<div class="form-group"><label for="codex_source">Source:</label><select id="codex_source" name="codex_source">
<option value="auto" {selected(codex_source, "auto")}>Auto</option>
<option value="cli" {selected(codex_source, "cli")}>CLI RPC</option>
<option value="session" {selected(codex_source, "session")}>Session files</option>
</select></div>
<div class="form-group"><label for="session_limit">Session File Limit:</label><input type="number" id="session_limit" name="session_limit" value="{session_limit}" min="1" max="100"></div>
</div>
<div class="settings-section">
<h2>Copilot Settings</h2>
<div class="form-group"><label class="checkbox-label"><input type="checkbox" name="copilot_enabled" {checked(copilot_enabled)}>Enable Copilot</label></div>
<div class="form-group"><label for="copilot_token">Token (optional):</label><input type="text" id="copilot_token" name="copilot_token" value="{copilot_token}" placeholder="Leave empty for auto-detect"><div class="help-text">Reads ~/.config/github-copilot/apps.json if empty</div></div>
</div>
<div class="form-actions"><button type="submit" class="btn">Save</button><a href="/" class="btn btn-secondary">Cancel</a></div>
</form>
</body>
</html>'''
