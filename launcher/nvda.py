from __future__ import annotations

import configparser
import ctypes
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time
import zipfile

from ctypes import wintypes


DEFAULT_NVDA_DOWNLOAD_URL = "https://download.nvaccess.org/releases/stable/nvda_2025.3.3.exe"
DEFAULT_ADDON_FILENAME = "speechLoggerMod2-silentSpeechOff-25.1.0.nvda-addon"
PROCESS_NAME = "nvda.exe"
MARKER_FILENAME = "workday-lens-nvda.json"
MOVEFILE_DELAY_UNTIL_REBOOT = 0x00000004
NVDA_SETTINGS_VERSION = "mouse-actions-screen-captures-v1"

DEFAULT_NVDA_CONFIG: dict[str, dict[str, bool | int]] = {
    "mouse": {
        "enableMouseTracking": True,
        "audioCoordinatesOnMouseMove": False,
        "reportObjectRoleOnMouseEnter": False,
    },
    "keyboard": {
        "speakCommandKeys": True,
    },
    "virtualBuffers": {
        "passThroughAudioIndication": False,
    },
    "audio": {
        "soundVolumeFollowsVoice": False,
        "soundVolume": 0,
    },
    "general": {
        "playStartAndExitSounds": False,
        "showWelcomeDialogAtStartup": False,
    },
    "presentation": {
        "reportKeyboardShortcuts": True,
        "reportObjectPositionInformation": False,
        "reportTooltips": False,
        "reportHelpBalloons": False,
        "reportObjectDescriptions": False,
        "reportDynamicContentChanges": True,
        "reportAutoSuggestionsWithSound": False,
    },
    "documentFormatting": {
        "reportTables": True,
        "reportTableCellCoords": False,
        "reportLinks": True,
        "reportLinkType": False,
        "reportGraphics": True,
        "reportHeadings": True,
        "reportLists": True,
        "reportLandmarks": True,
        "reportArticles": False,
        "reportFrames": False,
        "reportFigures": False,
        "reportClickable": False,
        "reportComments": False,
        "reportBookmarks": False,
        "reportSpellingErrors": True,
    },
}

if sys.platform.startswith("win"):
    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _KERNEL32.MoveFileExW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    _KERNEL32.MoveFileExW.restype = wintypes.BOOL
else:  # pragma: no cover
    _KERNEL32 = None


def _creation_flags() -> int:
    return int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)) | int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _normalized_windows_path(path: str | Path) -> str:
    return str(Path(path)).replace("/", "\\").rstrip("\\").lower()


def _powershell_executable() -> str:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(candidate if candidate.exists() else "powershell.exe")


def _ps_literal(text: str | Path) -> str:
    return str(text).replace("'", "''")


def _schedule_delete_on_reboot(path: Path) -> None:
    if _KERNEL32 is None:  # pragma: no cover
        raise OSError("Delete-on-reboot scheduling is only available on Windows.")
    if not _KERNEL32.MoveFileExW(str(path), None, MOVEFILE_DELAY_UNTIL_REBOOT):
        raise ctypes.WinError(ctypes.get_last_error())


def _schedule_tree_delete_on_reboot(target: Path) -> None:
    paths: list[Path] = []
    for current_root, dirnames, filenames in os.walk(target, topdown=False):
        root_path = Path(current_root)
        paths.extend(root_path / filename for filename in filenames)
        paths.extend(root_path / dirname for dirname in dirnames)
    paths.append(target)

    first_error: OSError | None = None
    for path in paths:
        if not path.exists():
            continue
        try:
            _schedule_delete_on_reboot(path)
        except OSError as exc:
            if first_error is None:
                first_error = exc
    if first_error is not None:
        raise first_error


def _start_background_delete_worker(target: Path, *, attempts: int = 90, delay_seconds: float = 2.0) -> bool:
    script = f"""
$path = '{_ps_literal(target)}'
for ($i = 0; $i -lt {attempts}; $i++) {{
  if (-not (Test-Path -LiteralPath $path)) {{
    exit 0
  }}
  try {{
    Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction Stop
    exit 0
  }} catch {{
    Start-Sleep -Milliseconds {int(delay_seconds * 1000)}
  }}
}}
exit 1
"""
    try:
        subprocess.Popen(
            [_powershell_executable(), "-NoProfile", "-NonInteractive", "-Command", script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            creationflags=_creation_flags(),
        )
        return True
    except OSError:
        return False


def _handle_remove_readonly(func, path: str, exc_info) -> None:
    try:
        os.chmod(path, stat.S_IWRITE)
    except OSError:
        pass
    func(path)


@dataclass(slots=True)
class NvdaMarker:
    addon_filename: str
    addon_name: str
    addon_sha256: str
    download_url: str
    installer_filename: str
    settings_version: str
    installed_at: str


@dataclass(slots=True)
class NvdaStatus:
    root_dir: Path
    exe_path: Path
    addon_dir: Path
    addon_package_path: Path
    marker_path: Path
    installer_path: Path | None
    installed: bool
    addon_installed: bool
    marker_current: bool
    running: bool

    @property
    def ready(self) -> bool:
        return self.installed and self.addon_installed and self.marker_current


@dataclass(slots=True)
class NvdaProcess:
    pid: int
    executable_path: str


class PortableNvdaManager:
    def __init__(self, app_root: Path, data_dir: Path) -> None:
        self.app_root = app_root
        self.data_dir = data_dir
        self.download_url = os.getenv("WFHS_NVDA_INSTALLER_URL", DEFAULT_NVDA_DOWNLOAD_URL).strip() or DEFAULT_NVDA_DOWNLOAD_URL
        self.root_dir = Path(os.getenv("WFHS_NVDA_ROOT", str(data_dir / "NVDA")))
        self.marker_path = self.root_dir / MARKER_FILENAME
        self.addon_package_path = self._resolve_addon_package_path()
        self.addon_name = self._read_addon_name(self.addon_package_path)
        self.addon_sha256 = self._file_sha256(self.addon_package_path)
        self.user_config_dir = self.root_dir / "userConfig"
        self.nvda_ini_path = self.user_config_dir / "nvda.ini"
        self.addon_dir = self.user_config_dir / "addons" / self.addon_name
        self.exe_path = self.root_dir / PROCESS_NAME
        self.installer_filename = Path(self.download_url).name or "nvda_portable_setup.exe"

    def status(self) -> NvdaStatus:
        installed = self.exe_path.exists()
        addon_installed = self.addon_dir.exists()
        running = self.is_running()
        marker_current = self._is_marker_current()
        return NvdaStatus(
            root_dir=self.root_dir,
            exe_path=self.exe_path,
            addon_dir=self.addon_dir,
            addon_package_path=self.addon_package_path,
            marker_path=self.marker_path,
            installer_path=self._find_installer_path(),
            installed=installed,
            addon_installed=addon_installed,
            marker_current=marker_current,
            running=running,
        )

    def ensure_installed(self, *, force_reinstall: bool = False) -> NvdaStatus:
        current = self.status()
        if current.ready and not force_reinstall:
            return current

        self.prepare_install()
        self.create_portable_copy()
        self.write_nvda_config()
        self.install_addon()
        return self.finalize_install()

    def prepare_install(self) -> None:
        self.stop(strict=False)
        time.sleep(2.0)
        if self.root_dir.exists():
            self._remove_tree_with_retries(self.root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def create_portable_copy(self) -> None:
        installer_path = self._resolve_installer_path()
        self.root_dir.mkdir(parents=True, exist_ok=True)
        script = f"""
$proc = Start-Process -FilePath '{_ps_literal(installer_path)}' -ArgumentList @('--create-portable-silent', '--portable-path={_ps_literal(self.root_dir)}') -PassThru -Wait -WindowStyle Hidden
exit $proc.ExitCode
"""
        result = subprocess.run(
            [_powershell_executable(), "-NoProfile", "-NonInteractive", "-Command", script],
            check=False,
            capture_output=True,
            text=True,
            creationflags=_creation_flags(),
        )
        if result.returncode != 0:
            raise RuntimeError(
                "Portable NVDA creation failed with exit code "
                f"{result.returncode}: {result.stdout or result.stderr or 'no output'}"
            )
        deadline = time.time() + 180
        while time.time() < deadline and not self.exe_path.exists():
            time.sleep(0.5)
        if not self.exe_path.exists():
            raise RuntimeError(
                "The bundled NVDA installer finished, but the portable copy did not appear at "
                f"{self.exe_path}. Check whether Windows blocked the installer or whether another NVDA setup flow is still open."
            )

    def install_addon(self) -> None:
        if not self.exe_path.exists():
            raise RuntimeError(f"Portable NVDA is missing: {self.exe_path}")
        if self.addon_dir.exists():
            self._remove_tree_with_retries(self.addon_dir)
        self.addon_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(self.addon_package_path) as archive:
            archive.extractall(self.addon_dir)

    def write_nvda_config(self) -> None:
        self.user_config_dir.mkdir(parents=True, exist_ok=True)
        parser = self._new_nvda_config_parser()
        if self.nvda_ini_path.exists():
            try:
                parser.read(self.nvda_ini_path, encoding="utf-8-sig")
            except (configparser.Error, OSError):
                parser = self._new_nvda_config_parser()

        for section, values in DEFAULT_NVDA_CONFIG.items():
            if not parser.has_section(section):
                parser.add_section(section)
            for key, value in values.items():
                parser.set(section, key, self._nvda_config_value(value))

        with self.nvda_ini_path.open("w", encoding="utf-8", newline="\n") as handle:
            parser.write(handle)

    def finalize_install(self) -> NvdaStatus:
        self.write_nvda_config()
        self._write_marker()
        return self.status()

    def start(self) -> NvdaStatus:
        current = self.ensure_installed()
        self.write_nvda_config()
        if current.running:
            return current

        process = subprocess.Popen(
            [str(self.exe_path), "--minimal"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=False,
            creationflags=_creation_flags(),
        )
        deadline = time.time() + 15
        while time.time() < deadline:
            refreshed = self.status()
            if refreshed.running:
                return refreshed
            if process.poll() is not None:
                raise RuntimeError(f"NVDA exited immediately with code {process.returncode}")
            time.sleep(0.3)
        raise RuntimeError("NVDA start was attempted, but the managed portable NVDA process did not appear in time.")

    def stop(self, *, strict: bool = True) -> bool:
        managed_processes = self._list_processes_under_root()
        if not managed_processes:
            return False

        remaining_pids = {process.pid for process in managed_processes}
        deadline = time.time() + 15
        while remaining_pids and time.time() < deadline:
            for pid in list(remaining_pids):
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F", "/T"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=_creation_flags(),
                )
            time.sleep(0.4)
            remaining_pids = {process.pid for process in self._list_processes_under_root()}

        if remaining_pids and strict:
            raise RuntimeError(f"Timed out while stopping managed NVDA (PID(s): {sorted(remaining_pids)}).")
        return not remaining_pids

    def uninstall(self) -> bool:
        self.stop(strict=False)
        time.sleep(2.0)
        if self.root_dir.exists():
            return self._remove_tree_with_retries(self.root_dir)
        return True

    def is_running(self) -> bool:
        return bool(self._list_managed_processes())

    def _list_managed_processes(self) -> list[NvdaProcess]:
        target_path = _normalized_windows_path(self.exe_path)
        return [
            process
            for process in self._list_nvda_processes()
            if _normalized_windows_path(process.executable_path) == target_path
        ]

    def _list_processes_under_root(self) -> list[NvdaProcess]:
        root_dir = self.root_dir
        if not root_dir.exists():
            return []

        root_literal = _ps_literal(_normalized_windows_path(root_dir))
        script = f"""
$root = '{root_literal}'
$rootPrefix = "$root\\"
$processes = Get-CimInstance Win32_Process |
  Where-Object {{
    $_.ExecutablePath -and (
      $_.ExecutablePath.ToLower() -eq $root -or
      $_.ExecutablePath.ToLower().StartsWith($rootPrefix)
    )
  }} |
  Select-Object @{{Name='pid';Expression={{$_.ProcessId}}}}, @{{Name='path';Expression={{$_.ExecutablePath}}}}
if ($null -eq $processes) {{
  '[]'
}} else {{
  @($processes) | ConvertTo-Json -Compress
}}
"""
        return self._run_process_query(script)

    def _list_nvda_processes(self) -> list[NvdaProcess]:
        if not sys.platform.startswith("win"):
            return []

        script = """
$processes = Get-CimInstance Win32_Process -Filter "Name='nvda.exe'" |
  Select-Object @{Name='pid';Expression={$_.ProcessId}}, @{Name='path';Expression={$_.ExecutablePath}}
if ($null -eq $processes) {
  '[]'
} else {
  @($processes) | ConvertTo-Json -Compress
}
"""
        return self._run_process_query(script)

    def _run_process_query(self, script: str) -> list[NvdaProcess]:
        result = subprocess.run(
            [_powershell_executable(), "-NoProfile", "-NonInteractive", "-Command", script],
            check=False,
            capture_output=True,
            text=True,
            creationflags=_creation_flags(),
        )
        if result.returncode != 0:
            return []

        raw = (result.stdout or "").strip()
        if not raw:
            return []

        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            return []

        rows = decoded if isinstance(decoded, list) else [decoded]
        processes: list[NvdaProcess] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            pid = row.get("pid")
            executable_path = row.get("path")
            if not isinstance(pid, int) or not executable_path:
                continue
            processes.append(NvdaProcess(pid=pid, executable_path=str(executable_path)))
        return processes

    @staticmethod
    def _new_nvda_config_parser() -> configparser.ConfigParser:
        parser = configparser.ConfigParser(interpolation=None)
        parser.optionxform = str
        return parser

    @staticmethod
    def _nvda_config_value(value: bool | int) -> str:
        if isinstance(value, bool):
            return "True" if value else "False"
        return str(value)

    def _resolve_addon_package_path(self) -> Path:
        override = os.getenv("WFHS_NVDA_ADDON_PATH", "").strip()
        candidates = []
        if override:
            candidates.append(Path(override))
        candidates.extend(
            [
                self.app_root / "runtime" / "nvda" / DEFAULT_ADDON_FILENAME,
                self.app_root / "packaging" / "nvda" / DEFAULT_ADDON_FILENAME,
            ]
        )
        for candidate in candidates:
            if candidate.exists():
                return candidate
        searched = ", ".join(str(path) for path in candidates)
        raise FileNotFoundError(f"Could not find bundled NVDA add-on package. Searched: {searched}")

    def _find_installer_path(self) -> Path | None:
        override = os.getenv("WFHS_NVDA_INSTALLER_PATH", "").strip()
        candidates = []
        if override:
            candidates.append(Path(override))
        candidates.extend(
            [
                self.app_root / "runtime" / "nvda" / self.installer_filename,
                self.app_root / "packaging" / "nvda" / self.installer_filename,
            ]
        )
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def _resolve_installer_path(self) -> Path:
        installer_path = self._find_installer_path()
        if installer_path is not None:
            return installer_path
        raise FileNotFoundError(
            "Bundled NVDA installer not found. "
            f"Place {self.installer_filename} in packaging\\nvda or set WFHS_NVDA_INSTALLER_PATH."
        )

    def _read_addon_name(self, addon_package_path: Path) -> str:
        with zipfile.ZipFile(addon_package_path) as archive:
            with archive.open("manifest.ini") as manifest_file:
                manifest_text = manifest_file.read().decode("utf-8", errors="replace")
        for raw_line in manifest_text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            if separator and key.strip().lower() == "name":
                return value.strip().strip('"')
        raise RuntimeError(f"Could not read add-on name from {addon_package_path}")

    def _read_marker(self) -> NvdaMarker | None:
        if not self.marker_path.exists():
            return None
        try:
            raw = json.loads(self.marker_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict):
            return None
        try:
            return NvdaMarker(**raw)
        except TypeError:
            return None

    def _is_marker_current(self) -> bool:
        marker = self._read_marker()
        if marker is None:
            return False
        return (
            marker.addon_filename == self.addon_package_path.name
            and marker.addon_name == self.addon_name
            and marker.addon_sha256 == self.addon_sha256
            and marker.download_url == self.download_url
            and marker.installer_filename == self.installer_filename
            and marker.settings_version == NVDA_SETTINGS_VERSION
        )

    def _write_marker(self) -> None:
        marker = NvdaMarker(
            addon_filename=self.addon_package_path.name,
            addon_name=self.addon_name,
            addon_sha256=self.addon_sha256,
            download_url=self.download_url,
            installer_filename=self.installer_filename,
            settings_version=NVDA_SETTINGS_VERSION,
            installed_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )
        self.marker_path.write_text(json.dumps(asdict(marker), indent=2), encoding="utf-8")

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _remove_tree_with_retries(self, target: Path, *, attempts: int = 30, delay_seconds: float = 1.0) -> bool:
        last_error: Exception | None = None
        for _ in range(attempts):
            if not target.exists():
                return True
            try:
                shutil.rmtree(target, onerror=_handle_remove_readonly)
                return True
            except FileNotFoundError:
                return True
            except PermissionError as exc:
                last_error = exc
                self.stop(strict=False)
                time.sleep(delay_seconds)
        if self._defer_tree_cleanup(target):
            return False
        if last_error is not None:
            raise last_error
        return True

    def _defer_tree_cleanup(self, target: Path) -> bool:
        if not sys.platform.startswith("win") or not target.exists():
            return False

        deferred_target = target
        renamed = False
        try:
            deferred_target = target.rename(self._pending_cleanup_path(target))
            renamed = True
        except OSError:
            deferred_target = target

        background_started = _start_background_delete_worker(deferred_target)
        delete_on_reboot_registered = False
        try:
            _schedule_tree_delete_on_reboot(deferred_target)
            delete_on_reboot_registered = True
        except OSError:
            delete_on_reboot_registered = False
        return renamed or background_started or delete_on_reboot_registered

    def _pending_cleanup_path(self, target: Path) -> Path:
        timestamp = time.strftime("%Y%m%d%H%M%S")
        candidate = target.with_name(f"{target.name}.pending-delete-{timestamp}")
        counter = 1
        while candidate.exists():
            candidate = target.with_name(f"{target.name}.pending-delete-{timestamp}-{counter}")
            counter += 1
        return candidate
