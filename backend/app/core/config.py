from __future__ import annotations

from dataclasses import asdict, dataclass
import base64
import json
import os
from pathlib import Path
from threading import RLock
from typing import Any


def _bool_from_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int_from_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _clamped_int(value: Any, default: int, minimum: int, maximum: int | None = None) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = default
    normalized = max(minimum, normalized)
    if maximum is not None:
        normalized = min(maximum, normalized)
    return normalized


def _app_data_dir() -> Path:
    override = os.getenv("WFHS_DATA_DIR")
    if override:
        return Path(override)
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "WorkdayLens"
    return Path("./data")


def _runtime_settings_path() -> Path:
    override = os.getenv("WFHS_RUNTIME_SETTINGS_PATH")
    if override:
        return Path(override)
    return _app_data_dir() / "runtime-settings.json"


OLD_WINDOW_TOKEN_LIMIT_DEFAULT = 3000
TRANSCRIPT_TOKEN_LIMIT_MAX = 64000


def _runtime_secrets_path() -> Path:
    override = os.getenv("WFHS_RUNTIME_SECRETS_PATH")
    if override:
        return Path(override)
    return _app_data_dir() / "runtime-secrets.json"


def _default_database_url() -> str:
    override = os.getenv("WFHS_DATABASE_URL")
    if override:
        return override
    database_path = (_app_data_dir() / "wfhs.db").resolve()
    return f"sqlite:///{database_path.as_posix()}"


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    CRYPTPROTECT_UI_FORBIDDEN = 0x01

    class _DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_byte)),
        ]

    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32


def _blob_from_bytes(raw: bytes):
    if not raw:
        raw = b"\x00"
    buffer = ctypes.create_string_buffer(raw) if os.name == "nt" else None
    if os.name != "nt" or buffer is None:
        return None, None
    blob = _DataBlob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    return blob, buffer


def _protect_secret(raw: str) -> dict[str, str]:
    if os.name != "nt":
        return {"mode": "local_file", "value": raw}
    source_blob, source_buffer = _blob_from_bytes(raw.encode("utf-8"))
    if source_blob is None or source_buffer is None:
        return {"mode": "local_file", "value": raw}
    protected_blob = _DataBlob()
    success = _crypt32.CryptProtectData(
        ctypes.byref(source_blob),
        "Workday Lens OpenAI API key",
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(protected_blob),
    )
    if not success:
        raise OSError("Could not encrypt the OpenAI API key with Windows DPAPI.")
    try:
        protected = ctypes.string_at(protected_blob.pbData, protected_blob.cbData)
    finally:
        if protected_blob.pbData:
            _kernel32.LocalFree(ctypes.cast(protected_blob.pbData, ctypes.c_void_p))
    return {
        "mode": "windows_dpapi",
        "value": base64.b64encode(protected).decode("ascii"),
    }


def _unprotect_secret(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if not isinstance(payload, dict):
        return ""
    mode = str(payload.get("mode") or "")
    value = payload.get("value")
    if not isinstance(value, str):
        return ""
    if mode != "windows_dpapi":
        return value
    if os.name != "nt":
        return ""
    encrypted = base64.b64decode(value.encode("ascii"))
    encrypted_blob, encrypted_buffer = _blob_from_bytes(encrypted)
    if encrypted_blob is None or encrypted_buffer is None:
        return ""
    decrypted_blob = _DataBlob()
    success = _crypt32.CryptUnprotectData(
        ctypes.byref(encrypted_blob),
        None,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(decrypted_blob),
    )
    if not success:
        return ""
    try:
        decrypted = ctypes.string_at(decrypted_blob.pbData, decrypted_blob.cbData)
    finally:
        if decrypted_blob.pbData:
            _kernel32.LocalFree(ctypes.cast(decrypted_blob.pbData, ctypes.c_void_p))
    return decrypted.decode("utf-8")


@dataclass(slots=True)
class RuntimeSettings:
    openai_api_key: str = ""
    display_name: str = ""
    llm_provider: str = "openai"
    fake_llm_mode: bool = False
    llm_model: str = "gpt-5-nano"
    dashboard_story_llm_enabled: bool = False
    dashboard_story_model: str = "gpt-5-mini"
    llm_timeout_seconds: int = 40
    llm_retry_limit: int = 3
    context_summary_limit: int = 5
    rollup_5m_context_summary_limit: int = 0
    rollup_15m_context_summary_limit: int = 0
    rollup_1h_context_summary_limit: int = 0
    rollup_4h_context_summary_limit: int = 0
    window_min_seconds: int = 60
    window_max_seconds: int = 60
    window_token_limit: int = 16000
    rollup_5m_raw_token_limit: int = 16000
    rollup_5m_enabled: bool = True
    rollup_15m_enabled: bool = True
    rollup_1h_enabled: bool = True
    rollup_4h_enabled: bool = True
    rollup_1d_enabled: bool = True
    rollup_1w_enabled: bool = True
    preferred_local_port: int = 3000


def _runtime_defaults_from_env() -> RuntimeSettings:
    llm_model = os.getenv("WFHS_LLM_MODEL", "gpt-5-nano").strip() or "gpt-5-nano"
    return RuntimeSettings(
        openai_api_key=os.getenv("WFHS_OPENAI_API_KEY", "").strip(),
        display_name=os.getenv("WFHS_DISPLAY_NAME", "").strip(),
        llm_provider=os.getenv("WFHS_LLM_PROVIDER", "openai").strip() or "openai",
        fake_llm_mode=_bool_from_env("WFHS_FAKE_LLM", False),
        llm_model=llm_model,
        dashboard_story_llm_enabled=_bool_from_env("WFHS_DASHBOARD_STORY_LLM_ENABLED", False),
        dashboard_story_model=os.getenv("WFHS_DASHBOARD_STORY_MODEL", "").strip() or "gpt-5-mini",
        llm_timeout_seconds=_int_from_env("WFHS_LLM_TIMEOUT_SECONDS", 40),
        llm_retry_limit=_int_from_env("WFHS_LLM_RETRY_LIMIT", 3),
        context_summary_limit=_int_from_env("WFHS_CONTEXT_SUMMARY_LIMIT", 5),
        rollup_5m_context_summary_limit=_int_from_env("WFHS_ROLLUP_5M_CONTEXT_SUMMARY_LIMIT", 0),
        rollup_15m_context_summary_limit=_int_from_env("WFHS_ROLLUP_15M_CONTEXT_SUMMARY_LIMIT", 0),
        rollup_1h_context_summary_limit=_int_from_env("WFHS_ROLLUP_1H_CONTEXT_SUMMARY_LIMIT", 0),
        rollup_4h_context_summary_limit=_int_from_env("WFHS_ROLLUP_4H_CONTEXT_SUMMARY_LIMIT", 0),
        window_min_seconds=_int_from_env("WFHS_WINDOW_MIN_SECONDS", 60),
        window_max_seconds=_int_from_env("WFHS_WINDOW_MAX_SECONDS", 60),
        window_token_limit=_int_from_env("WFHS_WINDOW_TOKEN_LIMIT", 16000),
        rollup_5m_raw_token_limit=_int_from_env("WFHS_ROLLUP_5M_RAW_TOKEN_LIMIT", 16000),
        rollup_5m_enabled=_bool_from_env("WFHS_ROLLUP_5M_ENABLED", True),
        rollup_15m_enabled=_bool_from_env("WFHS_ROLLUP_15M_ENABLED", True),
        rollup_1h_enabled=_bool_from_env("WFHS_ROLLUP_1H_ENABLED", True),
        rollup_4h_enabled=_bool_from_env("WFHS_ROLLUP_4H_ENABLED", True),
        rollup_1d_enabled=_bool_from_env("WFHS_ROLLUP_1D_ENABLED", True),
        rollup_1w_enabled=_bool_from_env("WFHS_ROLLUP_1W_ENABLED", True),
        preferred_local_port=_int_from_env("WFHS_PREFERRED_LOCAL_PORT", 3000),
    )


def _runtime_public_dict(runtime: RuntimeSettings) -> dict[str, Any]:
    data = asdict(runtime)
    data.pop("openai_api_key", None)
    return data


class RuntimeSecretStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = RLock()

    @property
    def storage_mode(self) -> str:
        return "windows_dpapi" if os.name == "nt" else "local_file"

    def get(self, name: str) -> str:
        with self._lock:
            payload = self._read().get(name)
            try:
                return _unprotect_secret(payload).strip()
            except Exception:
                return ""

    def set(self, name: str, value: str) -> None:
        protected = _protect_secret(value)
        with self._lock:
            data = self._read()
            data[name] = protected
            self._write(data)

    def delete(self, name: str) -> None:
        with self._lock:
            data = self._read()
            if name in data:
                data.pop(name, None)
                self._write(data)

    def _read(self) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")


class RuntimeSettingsStore:
    def __init__(self, path: Path, defaults: RuntimeSettings) -> None:
        self.path = path
        self.defaults = defaults
        self._lock = RLock()
        self._runtime = self._load()

    def get(self) -> RuntimeSettings:
        with self._lock:
            return RuntimeSettings(**asdict(self._runtime))

    def update(self, **values: Any) -> RuntimeSettings:
        with self._lock:
            data = _runtime_public_dict(self._runtime)
            for key, value in values.items():
                if value is not None and key in data:
                    data[key] = value
            self._runtime = self._normalize(RuntimeSettings(openai_api_key=self._runtime.openai_api_key, **data))
            self._write(self._runtime)
            return RuntimeSettings(**asdict(self._runtime))

    def replace_secret(self, value: str) -> RuntimeSettings:
        with self._lock:
            self._runtime = RuntimeSettings(openai_api_key=value, **_runtime_public_dict(self._runtime))
            return RuntimeSettings(**asdict(self._runtime))

    def _load(self) -> RuntimeSettings:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            runtime = self._normalize(RuntimeSettings(**asdict(self.defaults)))
            self._write(runtime)
            return runtime
        try:
            raw_data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            runtime = self._normalize(RuntimeSettings(**asdict(self.defaults)))
            self._write(runtime)
            return runtime
        merged = _runtime_public_dict(self.defaults)
        legacy_openai_api_key = ""
        if isinstance(raw_data, dict):
            for key in merged:
                if key in raw_data and raw_data[key] is not None:
                    merged[key] = raw_data[key]
            if (
                raw_data.get("window_token_limit") == OLD_WINDOW_TOKEN_LIMIT_DEFAULT
                and "rollup_5m_raw_token_limit" not in raw_data
            ):
                merged["window_token_limit"] = self.defaults.window_token_limit
            if isinstance(raw_data.get("openai_api_key"), str):
                legacy_openai_api_key = raw_data["openai_api_key"].strip()
        runtime = self._normalize(
            RuntimeSettings(openai_api_key=legacy_openai_api_key or self.defaults.openai_api_key, **merged)
        )
        self._write(runtime)
        return runtime

    def _normalize(self, runtime: RuntimeSettings) -> RuntimeSettings:
        display_name = " ".join(str(runtime.display_name).split())[:80]
        llm_provider = str(runtime.llm_provider or self.defaults.llm_provider).strip().lower()
        if llm_provider not in {"openai", "local_qwen35_4b"}:
            llm_provider = self.defaults.llm_provider
        llm_model = runtime.llm_model.strip() or self.defaults.llm_model
        dashboard_story_model = runtime.dashboard_story_model.strip() or self.defaults.dashboard_story_model or llm_model
        window_min_seconds = _clamped_int(runtime.window_min_seconds, self.defaults.window_min_seconds, 10)
        window_max_seconds = max(window_min_seconds, _clamped_int(runtime.window_max_seconds, self.defaults.window_max_seconds, 10))
        context_summary_limit = _clamped_int(runtime.context_summary_limit, self.defaults.context_summary_limit, 0)
        rollup_5m_context_summary_limit = _clamped_int(
            runtime.rollup_5m_context_summary_limit,
            self.defaults.rollup_5m_context_summary_limit,
            0,
            50,
        )
        rollup_15m_context_summary_limit = _clamped_int(
            runtime.rollup_15m_context_summary_limit,
            self.defaults.rollup_15m_context_summary_limit,
            0,
            50,
        )
        rollup_1h_context_summary_limit = _clamped_int(
            runtime.rollup_1h_context_summary_limit,
            self.defaults.rollup_1h_context_summary_limit,
            0,
            50,
        )
        rollup_4h_context_summary_limit = _clamped_int(
            runtime.rollup_4h_context_summary_limit,
            self.defaults.rollup_4h_context_summary_limit,
            0,
            50,
        )
        llm_timeout_seconds = _clamped_int(runtime.llm_timeout_seconds, self.defaults.llm_timeout_seconds, 1)
        llm_retry_limit = _clamped_int(runtime.llm_retry_limit, self.defaults.llm_retry_limit, 1)
        window_token_limit = _clamped_int(
            runtime.window_token_limit,
            self.defaults.window_token_limit,
            100,
            TRANSCRIPT_TOKEN_LIMIT_MAX,
        )
        rollup_5m_raw_token_limit = _clamped_int(
            runtime.rollup_5m_raw_token_limit,
            self.defaults.rollup_5m_raw_token_limit,
            0,
            TRANSCRIPT_TOKEN_LIMIT_MAX,
        )
        preferred_local_port = _clamped_int(runtime.preferred_local_port, self.defaults.preferred_local_port, 1024, 65535)
        return RuntimeSettings(
            openai_api_key=runtime.openai_api_key,
            display_name=display_name,
            llm_provider=llm_provider,
            fake_llm_mode=bool(runtime.fake_llm_mode),
            llm_model=llm_model,
            dashboard_story_llm_enabled=bool(runtime.dashboard_story_llm_enabled),
            dashboard_story_model=dashboard_story_model,
            llm_timeout_seconds=llm_timeout_seconds,
            llm_retry_limit=llm_retry_limit,
            context_summary_limit=context_summary_limit,
            rollup_5m_context_summary_limit=rollup_5m_context_summary_limit,
            rollup_15m_context_summary_limit=rollup_15m_context_summary_limit,
            rollup_1h_context_summary_limit=rollup_1h_context_summary_limit,
            rollup_4h_context_summary_limit=rollup_4h_context_summary_limit,
            window_min_seconds=window_min_seconds,
            window_max_seconds=window_max_seconds,
            window_token_limit=window_token_limit,
            rollup_5m_raw_token_limit=rollup_5m_raw_token_limit,
            rollup_5m_enabled=bool(runtime.rollup_5m_enabled),
            rollup_15m_enabled=bool(runtime.rollup_15m_enabled),
            rollup_1h_enabled=bool(runtime.rollup_1h_enabled),
            rollup_4h_enabled=bool(runtime.rollup_4h_enabled),
            rollup_1d_enabled=bool(runtime.rollup_1d_enabled),
            rollup_1w_enabled=bool(runtime.rollup_1w_enabled),
            preferred_local_port=preferred_local_port,
        )

    def _write(self, runtime: RuntimeSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(_runtime_public_dict(runtime), indent=2), encoding="utf-8")


class Settings:
    def __init__(self) -> None:
        defaults = _runtime_defaults_from_env()
        self.app_data_dir: Path = _app_data_dir()
        self.database_url: str = _default_database_url()
        self.runtime_settings_path: Path = _runtime_settings_path()
        self.runtime_secrets_path: Path = _runtime_secrets_path()
        self._runtime_store = RuntimeSettingsStore(self.runtime_settings_path, defaults)
        self._secret_store = RuntimeSecretStore(self.runtime_secrets_path)
        initial_key = defaults.openai_api_key or self._runtime_store.get().openai_api_key
        stored_key = self._secret_store.get("openai_api_key")
        key_to_use = stored_key or initial_key
        if initial_key and not stored_key:
            self._secret_store.set("openai_api_key", initial_key)
        self._runtime_store.replace_secret(key_to_use)
        self.api_cors_origins: tuple[str, ...] = tuple(
            origin.strip()
            for origin in os.getenv("WFHS_API_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
            if origin.strip()
        )
        self.api_cors_origin_regex: str | None = (
            os.getenv("WFHS_API_CORS_ORIGIN_REGEX", "") or r"http://(localhost|127\.0\.0\.1)(:\d+)?$"
        )

    def runtime(self) -> RuntimeSettings:
        runtime = self._runtime_store.get()
        runtime.openai_api_key = self._secret_store.get("openai_api_key")
        return runtime

    def update_runtime(self, **values: Any) -> RuntimeSettings:
        openai_api_key = values.pop("openai_api_key", None)
        if openai_api_key is not None:
            normalized_key = str(openai_api_key).strip()
            if normalized_key:
                self._secret_store.set("openai_api_key", normalized_key)
                self._runtime_store.replace_secret(normalized_key)
        runtime = self._runtime_store.update(**values)
        runtime.openai_api_key = self._secret_store.get("openai_api_key")
        return runtime

    def delete_openai_api_key(self) -> RuntimeSettings:
        self._secret_store.delete("openai_api_key")
        runtime = self._runtime_store.replace_secret("")
        runtime.openai_api_key = ""
        return runtime

    def openai_api_key_configured(self) -> bool:
        return bool(self._secret_store.get("openai_api_key"))

    def openai_api_key_last4(self) -> str | None:
        key = self._secret_store.get("openai_api_key")
        if len(key) < 4:
            return None
        return key[-4:]

    @property
    def openai_api_key_storage(self) -> str:
        return self._secret_store.storage_mode

    @property
    def openai_api_key(self) -> str:
        return self.runtime().openai_api_key

    @property
    def fake_llm_mode(self) -> bool:
        return self.runtime().fake_llm_mode

    @property
    def llm_provider(self) -> str:
        runtime = self.runtime()
        return "fake" if runtime.fake_llm_mode else runtime.llm_provider

    def openai_required(self) -> bool:
        runtime = self.runtime()
        return not runtime.fake_llm_mode and runtime.llm_provider == "openai"

    @property
    def llm_model(self) -> str:
        return self.runtime().llm_model

    @property
    def dashboard_story_llm_enabled(self) -> bool:
        return self.runtime().dashboard_story_llm_enabled

    @property
    def dashboard_story_model(self) -> str:
        return self.runtime().dashboard_story_model

    @property
    def llm_timeout_seconds(self) -> int:
        return self.runtime().llm_timeout_seconds

    @property
    def llm_retry_limit(self) -> int:
        return self.runtime().llm_retry_limit

    @property
    def context_summary_limit(self) -> int:
        return self.runtime().context_summary_limit

    @property
    def rollup_5m_context_summary_limit(self) -> int:
        return self.runtime().rollup_5m_context_summary_limit

    @property
    def rollup_15m_context_summary_limit(self) -> int:
        return self.runtime().rollup_15m_context_summary_limit

    @property
    def rollup_1h_context_summary_limit(self) -> int:
        return self.runtime().rollup_1h_context_summary_limit

    @property
    def rollup_4h_context_summary_limit(self) -> int:
        return self.runtime().rollup_4h_context_summary_limit

    def rollup_context_summary_limit(self, level: str) -> int:
        return {
            "5m": self.rollup_5m_context_summary_limit,
            "15m": self.rollup_15m_context_summary_limit,
            "1h": self.rollup_1h_context_summary_limit,
            "4h": self.rollup_4h_context_summary_limit,
        }.get(level, 0)

    @property
    def window_min_seconds(self) -> int:
        return self.runtime().window_min_seconds

    @property
    def window_max_seconds(self) -> int:
        return self.runtime().window_max_seconds

    @property
    def window_token_limit(self) -> int:
        return self.runtime().window_token_limit

    @property
    def rollup_5m_raw_token_limit(self) -> int:
        return self.runtime().rollup_5m_raw_token_limit

    @property
    def rollup_5m_enabled(self) -> bool:
        return self.runtime().rollup_5m_enabled

    @property
    def rollup_15m_enabled(self) -> bool:
        return self.runtime().rollup_15m_enabled

    @property
    def rollup_1h_enabled(self) -> bool:
        return self.runtime().rollup_1h_enabled

    @property
    def rollup_4h_enabled(self) -> bool:
        return self.runtime().rollup_4h_enabled

    @property
    def rollup_1d_enabled(self) -> bool:
        return self.runtime().rollup_1d_enabled

    @property
    def rollup_1w_enabled(self) -> bool:
        return self.runtime().rollup_1w_enabled

    def rollup_enabled(self, level: str) -> bool:
        return {
            "5m": self.rollup_5m_enabled,
            "15m": self.rollup_15m_enabled,
            "1h": self.rollup_1h_enabled,
            "4h": self.rollup_4h_enabled,
            "1d": self.rollup_1d_enabled,
            "1w": self.rollup_1w_enabled,
        }.get(level, False)

    @property
    def preferred_local_port(self) -> int:
        return self.runtime().preferred_local_port


settings = Settings()
