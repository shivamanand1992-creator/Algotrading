import os
import sys
from pathlib import Path
from typing import Dict, List
import importlib.util

# Add parent directory to path to import existing modules
parent_dir = str(Path(__file__).parent.parent)
sys.path.insert(0, parent_dir)

# Import the parent config module explicitly
config_path = Path(__file__).parent.parent / "config" / "__init__.py"
spec = importlib.util.spec_from_file_location("parent_config", config_path)
parent_config_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent_config_module)
load_yaml_config = parent_config_module.load_config


class BackendConfig:
    def __init__(self):
        # Load existing config from config.yaml
        self.trading_config = load_yaml_config()

        # Backend-specific settings
        self.host = os.getenv("BACKEND_HOST", "0.0.0.0")
        self.port = int(os.getenv("BACKEND_PORT", "8000"))
        self.cors_origins = self._get_cors_origins()
        self.websocket_heartbeat = 30

    def _get_cors_origins(self) -> List[str]:
        cors = os.getenv("CORS_ORIGINS", "http://localhost:3000")
        return [origin.strip() for origin in cors.split(",")]

    @property
    def database_url(self) -> str:
        return os.getenv("DATABASE_URL", "sqlite:///logs/trades.db")


# Singleton instance
config = BackendConfig()
