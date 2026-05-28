import json
import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger("KindleVibe")

CONFIG_FILE = Path(__file__).parent / "config.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "server": {
        "port": 8080,
        "host": "0.0.0.0"
    },
    "refresh": {
        "interval_seconds": 300,
        "page_refresh_ms": 300000
    },
    "codex": {
        "enabled": True,
        "source": "auto",
        "session_file_limit": 10
    },
    "copilot": {
        "enabled": True,
        "token": ""
    },
    "display": {
        "show_credits": True,
        "show_plan_type": True,
        "show_data_source": True,
        "show_last_updated": True
    }
}


class Config:
    _instance = None
    _data: Dict[str, Any] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def load(self):
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, "r") as f:
                    override = json.load(f)
                self._data = self._merge(DEFAULT_CONFIG, override)
                logger.info(f"Config loaded from {CONFIG_FILE}")
            else:
                self._data = dict(DEFAULT_CONFIG)
                self.save()
        except Exception as e:
            logger.error(f"Config load error: {e}")
            self._data = dict(DEFAULT_CONFIG)

    def save(self) -> bool:
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self._data, f, indent=2)
            logger.info(f"Config saved to {CONFIG_FILE}")
            return True
        except Exception as e:
            logger.error(f"Config save error: {e}")
            return False

    def get(self, *keys: str, default=None):
        val = self._data
        for k in keys:
            if isinstance(val, dict):
                val = val.get(k, {})
            else:
                return default
        return val if val != {} else default

    def set(self, *args):
        if len(args) < 2:
            return
        keys = args[:-1]
        value = args[-1]
        val = self._data
        for k in keys[:-1]:
            if k not in val or not isinstance(val[k], dict):
                val[k] = {}
            val = val[k]
        val[keys[-1]] = value

    @staticmethod
    def _merge(base: Dict, override: Dict) -> Dict:
        result = dict(base)
        for k, v in override.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = Config._merge(result[k], v)
            else:
                result[k] = v
        return result

    @property
    def data(self) -> Dict:
        return self._data


config = Config()
