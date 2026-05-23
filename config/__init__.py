"""Config loader utility."""

import os
import re
import yaml
from pathlib import Path
from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / ".env")


def _expand_env_vars(obj):
    """Recursively expand ${VAR} in config values."""
    if isinstance(obj, str):
        return re.sub(r"\$\{([^}]+)\}", lambda m: os.environ.get(m.group(1), ""), obj)
    elif isinstance(obj, dict):
        return {k: _expand_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_expand_env_vars(v) for v in obj]
    return obj


def load_config(path: str = None) -> dict:
    config_path = Path(path) if path else _ROOT / "config" / "config.yaml"
    with open(config_path) as f:
        raw = yaml.safe_load(f)
    return _expand_env_vars(raw)
