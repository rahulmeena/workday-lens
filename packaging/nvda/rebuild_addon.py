"""Rebuild the modified Speech Logger add-on from editable source."""
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
ADDON = ROOT / "speechLoggerMod2-silentSpeechOff-25.1.0.nvda-addon"


def rebuild() -> None:
    files = {}
    for folder in [ROOT / "addon_src", ROOT / "addon_overrides"]:
        for path in folder.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}:
                files[path.relative_to(folder).as_posix()] = path
    if "manifest.ini" not in files:
        raise RuntimeError("Missing add-on source manifest")
    with zipfile.ZipFile(ADDON, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, path in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    print(f"Built {ADDON.name} from {len(files)} source files")


if __name__ == "__main__":
    rebuild()
