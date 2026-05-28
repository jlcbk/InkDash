#!/usr/bin/env python3
import json
import logging
import socket
import subprocess
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from cache import ThrottleCache
from codex import CodexUsage, fetch_codex_usage
from config import config
from copilot import CopilotUsage, fetch_copilot_usage
from templates import generate_main_html, generate_settings_html

logger = logging.getLogger("KindleVibe")


def setup_logging():
    logger.setLevel(logging.DEBUG)
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    file_h = logging.FileHandler(log_dir / "kindlevibe.log", encoding="utf-8")
    file_h.setLevel(logging.DEBUG)
    file_h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s"))
    logger.addHandler(console)
    logger.addHandler(file_h)


def get_local_ip() -> str:
    vpn_prefixes = ("utun", "tun", "tap", "ppp", "ipsec", "wg")
    try:
        result = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            current_iface = None
            for line in result.stdout.split("\n"):
                if not line.startswith(" ") and ":" in line:
                    current_iface = line.split(":")[0].strip()
                if "inet " in line and current_iface and not current_iface.startswith(vpn_prefixes) and "127.0.0.1" not in line:
                    parts = line.strip().split()
                    for i, p in enumerate(parts):
                        if p == "inet" and i + 1 < len(parts):
                            ip = parts[i + 1]
                            if ip.startswith(("192.168.", "10.", "172.")):
                                return ip
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class SharedState:
    def __init__(self):
        self.codex = CodexUsage()
        self.copilot = CopilotUsage()
        self.lock = threading.Lock()
        self._codex_cache = ThrottleCache(ttl_seconds=120)
        self._copilot_cache = ThrottleCache(ttl_seconds=120)

    def update(self):
        while True:
            interval = config.get("refresh", "interval_seconds", default=300)

            if config.get("codex", "enabled", default=True):
                data, err = self._codex_cache.get(fetch_codex_usage)
                if data and not err:
                    with self.lock:
                        self.codex = data
                        logger.info(f"Codex: 5h={data.five_hour_percent_left}%, weekly={data.weekly_percent_left}%")
                elif err:
                    logger.warning(f"Codex error: {err}")

            if config.get("copilot", "enabled", default=True):
                data, err = self._copilot_cache.get(fetch_copilot_usage)
                if data and not err:
                    with self.lock:
                        self.copilot = data
                        logger.info(f"Copilot: premium={data.premium_percent}%, chat={data.chat_percent}%")
                elif err:
                    logger.warning(f"Copilot error: {err}")

            time.sleep(interval)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            with state.lock:
                html = generate_main_html(state.codex, state.copilot)
            self._send_html(html)

        elif path == "/settings":
            self._send_html(generate_settings_html())

        elif path == "/api/usage":
            with state.lock:
                payload = {
                    "codex": state.codex.to_dict(),
                    "copilot": state.copilot.to_dict(),
                }
            self._send_json(payload)

        elif path == "/api/config":
            self._send_json(config.data)

        else:
            self.send_response(404)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>404 Not Found</h1>")

    def do_POST(self):
        if self.path == "/settings":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            params = parse_qs(body)

            try:
                if "port" in params:
                    config.set("server", "port", int(params["port"][0]))
                if "host" in params:
                    config.set("server", "host", params["host"][0])
                if "refresh_interval" in params:
                    config.set("refresh", "interval_seconds", max(30, min(3600, int(params["refresh_interval"][0]))))
                if "page_refresh" in params:
                    config.set("refresh", "page_refresh_ms", max(30, min(3600, int(params["page_refresh"][0]))) * 1000)

                config.set("codex", "enabled", "codex_enabled" in params)
                if "codex_source" in params:
                    config.set("codex", "source", params["codex_source"][0])
                if "session_limit" in params:
                    config.set("codex", "session_file_limit", max(1, min(100, int(params["session_limit"][0]))))

                config.set("copilot", "enabled", "copilot_enabled" in params)
                if "copilot_token" in params:
                    config.set("copilot", "token", params["copilot_token"][0])

                ok = config.save()
                msg = "Settings saved!" if ok else "Failed to save!"
                self._send_html(generate_settings_html(msg, "success" if ok else "error"))
            except Exception as e:
                logger.exception("Settings save error")
                self._send_html(generate_settings_html(f"Error: {e}", "error"))
        else:
            self.send_response(404)
            self.end_headers()

    def _send_html(self, html: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _send_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode("utf-8"))

    def log_message(self, fmt, *args):
        logger.debug(f"HTTP {args[0]}")


def main():
    setup_logging()
    config.load()

    port = config.get("server", "port", default=8080)
    host = config.get("server", "host", default="0.0.0.0")
    local_ip = get_local_ip()

    global state
    state = SharedState()

    refresh_thread = threading.Thread(target=state.update, daemon=True)
    refresh_thread.start()
    logger.info("Background refresh started")

    server = HTTPServer((host, port), Handler)
    print(f"\n{'=' * 50}")
    print(f"  KindleVibe-Python Started!")
    print(f"{'=' * 50}")
    print(f"\n  Local:   http://localhost:{port}")
    print(f"  Network: http://{local_ip}:{port}")
    print(f"\n  Open on your Kindle")
    print(f"{'=' * 50}\n")
    logger.info(f"Serving on http://{local_ip}:{port}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
