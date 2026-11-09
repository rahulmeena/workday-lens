from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
from typing import TextIO
import webbrowser

import httpx
import uvicorn

from backend.app.core.config import settings


APP_NAME = "Workday Lens"
BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8000
FRONTEND_HOST = "127.0.0.1"
READINESS_TIMEOUT_SECONDS = 60
_STDIO_REDIRECT: TextIO | None = None


def _creation_flags() -> int:
    return int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)) | int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _ensure_process_stdio(log_dir: Path) -> None:
    global _STDIO_REDIRECT
    if sys.stdout is not None and sys.stderr is not None:
        return
    if _STDIO_REDIRECT is None or _STDIO_REDIRECT.closed:
        log_dir.mkdir(parents=True, exist_ok=True)
        _STDIO_REDIRECT = (log_dir / "launcher.log").open("a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = _STDIO_REDIRECT
    if sys.stderr is None:
        sys.stderr = _STDIO_REDIRECT


def _app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _where(executable: str) -> Path | None:
    resolved = shutil.which(executable)
    return Path(resolved) if resolved else None


def _is_port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def _pick_frontend_port(preferred_port: int) -> int:
    if _is_port_available(FRONTEND_HOST, preferred_port):
        return preferred_port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((FRONTEND_HOST, 0))
        return int(sock.getsockname()[1])


def _wait_for_http_ready(url: str, *, timeout_seconds: int = READINESS_TIMEOUT_SECONDS) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    with httpx.Client(follow_redirects=True, timeout=5.0) as client:
        while time.time() < deadline:
            try:
                response = client.get(url)
                if response.status_code < 500:
                    return
            except httpx.HTTPError as exc:
                last_error = exc
            time.sleep(0.5)
    if last_error:
        raise RuntimeError(f"Timed out waiting for {url}: {last_error}") from last_error
    raise RuntimeError(f"Timed out waiting for {url}")


@dataclass(slots=True)
class FrontendState:
    port: int
    url: str
    mode: str


class ManagedBackendServer:
    def __init__(self) -> None:
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        if not _is_port_available(BACKEND_HOST, BACKEND_PORT):
            raise RuntimeError(
                f"Backend port {BACKEND_PORT} is already in use on {BACKEND_HOST}. "
                "Stop the other local service or change the backend port before launching Workday Lens."
            )
        from backend.app.main import app as backend_app

        config = uvicorn.Config(
            backend_app,
            host=BACKEND_HOST,
            port=BACKEND_PORT,
            log_level="info",
        )
        server = uvicorn.Server(config)
        server.install_signal_handlers = lambda: None
        thread = threading.Thread(target=server.run, name="WorkdayLensBackend", daemon=True)
        self._server = server
        self._thread = thread
        thread.start()

    def stop(self) -> None:
        server = self._server
        thread = self._thread
        if server is None or thread is None:
            return
        server.should_exit = True
        thread.join(timeout=20)
        self._server = None
        self._thread = None


class ManagedFrontendProcess:
    def __init__(self, app_root: Path, log_dir: Path) -> None:
        self.app_root = app_root
        self.repo_frontend_dir = app_root / "frontend"
        self.packaged_frontend_dir = app_root / "runtime" / "frontend"
        self.packaged_node = app_root / "runtime" / "node" / ("node.exe" if sys.platform.startswith("win") else "node")
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._process: subprocess.Popen[str] | None = None
        self._log_handle: TextIO | None = None
        self._state: FrontendState | None = None

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def state(self) -> FrontendState | None:
        return self._state

    def start(self, port: int) -> FrontendState:
        if self.running and self._state is not None and self._state.port == port:
            return self._state
        self.stop()
        command, cwd, mode = self._frontend_command(port)
        log_path = self.log_dir / "frontend.log"
        self._log_handle = log_path.open("a", encoding="utf-8")
        env = dict(os.environ)
        env["PORT"] = str(port)
        env["HOSTNAME"] = FRONTEND_HOST
        env["NEXT_TELEMETRY_DISABLED"] = "1"
        env["NEXT_PUBLIC_API_BASE_URL"] = f"http://{BACKEND_HOST}:{BACKEND_PORT}/api/v1"
        self._process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=_creation_flags(),
        )
        self._state = FrontendState(port=port, url=f"http://{FRONTEND_HOST}:{port}", mode=mode)
        return self._state

    def stop(self) -> None:
        process = self._process
        if process is not None and process.poll() is None:
            if sys.platform.startswith("win"):
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=_creation_flags(),
                )
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            else:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
        self._process = None
        self._state = None
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None

    def _frontend_command(self, port: int) -> tuple[list[str], Path, str]:
        packaged_server = self.packaged_frontend_dir / "server.js"
        if packaged_server.exists():
            if not self.packaged_node.exists():
                raise RuntimeError(f"Packaged frontend found but Node runtime is missing: {self.packaged_node}")
            return [str(self.packaged_node), str(packaged_server)], self.packaged_frontend_dir, "standalone"

        standalone_server = self.repo_frontend_dir / ".next" / "standalone" / "server.js"
        system_node = _where("node.exe" if sys.platform.startswith("win") else "node")
        if standalone_server.exists() and system_node is not None:
            self._ensure_repo_standalone_ready()
            return [str(system_node), str(standalone_server)], standalone_server.parent, "repo-standalone"

        self._ensure_dev_build()
        npm_command = self._npm_command()
        return (
            [
                str(npm_command),
                "run",
                "start",
                "--",
                "--hostname",
                FRONTEND_HOST,
                "--port",
                str(port),
            ],
            self.repo_frontend_dir,
            "npm-start",
        )

    def _ensure_repo_standalone_ready(self) -> None:
        standalone_dir = self.repo_frontend_dir / ".next" / "standalone"
        static_dir = self.repo_frontend_dir / ".next" / "static"
        standalone_static = standalone_dir / ".next" / "static"
        if not standalone_dir.exists():
            self._ensure_dev_build()
        if static_dir.exists():
            standalone_static.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(static_dir, standalone_static, dirs_exist_ok=True)
        public_dir = self.repo_frontend_dir / "public"
        standalone_public = standalone_dir / "public"
        if public_dir.exists():
            shutil.copytree(public_dir, standalone_public, dirs_exist_ok=True)

    def _ensure_dev_build(self) -> None:
        build_marker = self.repo_frontend_dir / ".next" / "BUILD_ID"
        if build_marker.exists():
            return
        if not (self.repo_frontend_dir / "node_modules").exists():
            raise RuntimeError(
                "Frontend dependencies are missing. Run `npm install` in the frontend folder before launching Workday Lens."
            )
        build_log = self.log_dir / "frontend-build.log"
        with build_log.open("a", encoding="utf-8") as handle:
            subprocess.run(
                [str(self._npm_command()), "run", "build"],
                cwd=self.repo_frontend_dir,
                stdin=subprocess.DEVNULL,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=_creation_flags(),
                check=True,
            )

    @staticmethod
    def _npm_command() -> Path:
        executable = "npm.cmd" if sys.platform.startswith("win") else "npm"
        resolved = _where(executable)
        if resolved is None:
            raise RuntimeError("npm is not installed or is not available on PATH.")
        return resolved


class WorkdayLensLauncher:
    def __init__(self, app_root: Path) -> None:
        self.app_root = app_root
        self.data_dir = settings.runtime_settings_path.parent
        self.log_dir = self.data_dir / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        # Windowed PyInstaller launches without stdout/stderr. Give libraries a
        # real stream so uvicorn and traceback logging can initialize safely.
        _ensure_process_stdio(self.log_dir)
        self.backend = ManagedBackendServer()
        self.frontend = ManagedFrontendProcess(app_root, self.log_dir)
        self.frontend_state: FrontendState | None = None
        self._lock = threading.RLock()

    @property
    def backend_health_url(self) -> str:
        return f"http://{BACKEND_HOST}:{BACKEND_PORT}/api/v1/health"

    @property
    def frontend_url(self) -> str:
        if self.frontend_state is None:
            return f"http://{FRONTEND_HOST}:{settings.preferred_local_port}"
        return self.frontend_state.url

    def start_services(self, *, frontend_port_override: int | None = None) -> None:
        with self._lock:
            preferred_port = frontend_port_override or settings.preferred_local_port
            selected_port = _pick_frontend_port(preferred_port)
            self.backend.start()
            _wait_for_http_ready(self.backend_health_url)
            self.frontend_state = self.frontend.start(selected_port)
            _wait_for_http_ready(self.frontend_state.url)

    def restart_services(self) -> None:
        with self._lock:
            selected_port = self.frontend_state.port if self.frontend_state else None
            self.stop_services()
            self.start_services(frontend_port_override=selected_port)

    def stop_services(self, *, strict: bool = False) -> None:
        with self._lock:
            errors: list[str] = []
            try:
                self.frontend.stop()
            except Exception as exc:
                errors.append(f"Frontend stop failed: {exc}")
            try:
                self.backend.stop()
            except Exception as exc:
                errors.append(f"Backend stop failed: {exc}")
            self.frontend_state = None
            if errors and strict:
                raise RuntimeError("; ".join(errors))

    def open_dashboard(self) -> None:
        with self._lock:
            if not self.frontend.running:
                self.start_services()
            webbrowser.open(self.frontend_url)

    def run_headless(self, *, open_browser: bool, frontend_port_override: int | None = None) -> None:
        self.start_services(frontend_port_override=frontend_port_override)
        if open_browser:
            self.open_dashboard()
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop_services()

    def run_once(self, *, frontend_port_override: int | None = None) -> None:
        self.start_services(frontend_port_override=frontend_port_override)
        try:
            mode = self.frontend_state.mode if self.frontend_state else "unknown"
            print(f"Backend ready at {self.backend_health_url}")
            print(f"Dashboard ready at {self.frontend_url}")
            print(f"Frontend mode: {mode}")
            print("Capture helper: run the native macOS menu-bar app to start observation.")
        finally:
            self.stop_services()

    def run_tray(self, *, open_browser: bool, frontend_port_override: int | None = None) -> None:
        self.start_services(frontend_port_override=frontend_port_override)
        if open_browser:
            self.open_dashboard()
        self._run_system_tray()

    def _run_system_tray(self) -> None:
        try:
            import pystray
            from PIL import Image, ImageDraw
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "Tray dependencies are missing. Install launcher/requirements.txt or run with --headless."
            ) from exc

        shutdown_requested = threading.Event()

        def open_dashboard(icon: pystray.Icon, item: pystray.MenuItem) -> None:
            self.open_dashboard()
            icon.update_menu()

        def restart_services(icon: pystray.Icon, item: pystray.MenuItem) -> None:
            self.restart_services()
            icon.update_menu()

        def quit_launcher(icon: pystray.Icon, item: pystray.MenuItem) -> None:
            shutdown_requested.set()
            try:
                icon.visible = False
            except Exception:
                pass
            icon.stop()

        icon = pystray.Icon(
            "workday-lens",
            self._create_icon(Image, ImageDraw),
            APP_NAME,
            menu=pystray.Menu(
                pystray.MenuItem("Open Dashboard", open_dashboard),
                pystray.MenuItem("Restart Services", restart_services),
                pystray.MenuItem(
                    lambda item: f"Dashboard: {self.frontend_url}",
                    lambda icon, item: None,
                    enabled=False,
                ),
                pystray.MenuItem(
                    lambda item: f"Frontend: {self.frontend_state.mode if self.frontend_state else 'idle'}",
                    lambda icon, item: None,
                    enabled=False,
                ),
                pystray.MenuItem(
                    lambda item: "Capture: managed by the macOS menu-bar helper",
                    lambda icon, item: None,
                    enabled=False,
                ),
                pystray.MenuItem("Quit", quit_launcher),
            ),
        )
        try:
            icon.run()
        finally:
            try:
                icon.visible = False
            except Exception:
                pass
            if shutdown_requested.is_set():
                self.stop_services(strict=False)

    def _icon_asset_candidates(self) -> tuple[Path, ...]:
        return (
            self.app_root / "runtime" / "assets" / "workday-lens-friendly.png",
            self.app_root / "runtime" / "assets" / "workday-lens-dune.png",
            self.app_root / "packaging" / "assets" / "workday-lens-friendly.png",
            self.app_root / "packaging" / "assets" / "workday-lens-dune.png",
        )

    def _create_icon(self, image_module, draw_module):
        resampling = getattr(getattr(image_module, "Resampling", image_module), "LANCZOS")
        for candidate in self._icon_asset_candidates():
            if not candidate.exists():
                continue
            with image_module.open(candidate) as source_image:
                return source_image.convert("RGBA").resize((64, 64), resampling)

        image = image_module.new("RGBA", (64, 64), (245, 239, 229, 255))
        draw = draw_module.Draw(image)
        draw.rounded_rectangle((5, 5, 59, 59), radius=18, fill=(43, 24, 17, 255))
        draw.ellipse((14, 12, 50, 44), fill=(223, 131, 55, 255))
        draw.pieslice((12, 14, 52, 46), start=200, end=340, fill=(255, 199, 110, 235))
        draw.polygon(((8, 45), (24, 31), (44, 37), (58, 27), (58, 59), (8, 59)), fill=(116, 64, 36, 255))
        draw.polygon(((6, 59), (18, 44), (34, 49), (50, 39), (58, 44), (58, 59)), fill=(196, 121, 59, 255))
        draw.ellipse((22, 26, 42, 40), fill=(50, 24, 16, 210))
        draw.ellipse((27, 29, 37, 39), fill=(244, 189, 98, 235))
        return image


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch the local Workday Lens macOS beta backend and dashboard.")
    parser.add_argument("--headless", action="store_true", help="Run the launcher without a tray icon.")
    parser.add_argument("--once", action="store_true", help="Start services, verify readiness, print URLs, and exit.")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open the dashboard in a browser.")
    parser.add_argument("--frontend-port", type=int, help="Override the saved preferred local dashboard port.")
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    launcher = WorkdayLensLauncher(_app_root())
    try:
        if args.once:
            launcher.run_once(frontend_port_override=args.frontend_port)
            return
        if args.headless:
            launcher.run_headless(
                open_browser=not args.no_browser,
                frontend_port_override=args.frontend_port,
            )
            return
        launcher.run_tray(
            open_browser=not args.no_browser,
            frontend_port_override=args.frontend_port,
        )
    except Exception:
        try:
            launcher.stop_services()
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
