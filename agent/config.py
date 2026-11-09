from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


def _default_data_dir() -> Path:
    override = os.getenv("WFHS_DATA_DIR")
    if override:
        return Path(override)
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "WorkdayLens"
    return Path("data")


@dataclass(slots=True)
class AgentSettings:
    data_dir: str = str(_default_data_dir())
    store_path: str = os.getenv("WFHS_AGENT_STORE_PATH", str(_default_data_dir() / "agent.db"))
    screen_reader_host: str = os.getenv("WFHS_SCREEN_READER_HOST", "127.0.0.1")
    screen_reader_port: int = int(os.getenv("WFHS_SCREEN_READER_PORT", "12345"))
    api_base_url: str = os.getenv("WFHS_API_BASE_URL", "http://127.0.0.1:8000/api/v1")
    session_id: str = os.getenv("WFHS_SESSION_ID", "employee-1")
    flush_interval_seconds: float = float(os.getenv("WFHS_FLUSH_INTERVAL_SECONDS", "1.0"))
    http_timeout_seconds: float = float(os.getenv("WFHS_HTTP_TIMEOUT_SECONDS", "5.0"))
    batch_size: int = int(os.getenv("WFHS_BATCH_SIZE", "25"))
    max_retry_attempts: int = int(os.getenv("WFHS_MAX_RETRY_ATTEMPTS", "5"))


settings = AgentSettings()
