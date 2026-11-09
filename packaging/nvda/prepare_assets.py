"""Fetch the pinned NVDA runtime and build the add-on from public source."""
from pathlib import Path
import argparse
import hashlib
import json
import urllib.request
from rebuild_addon import rebuild

ROOT = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-installer", action="store_true")
    args = parser.parse_args()
    metadata = json.loads((ROOT / "provenance.json").read_text())
    if not args.skip_installer:
        name = f"nvda_{metadata['nvda_version']}.exe"
        target = ROOT / name
        expected = metadata["nvda_sha256"]
        if not target.exists():
            temporary = target.with_suffix(".download")
            try:
                url = f"https://download.nvaccess.org/releases/{metadata['nvda_version']}/{name}"
                urllib.request.urlretrieve(url, temporary)
                if hashlib.sha256(temporary.read_bytes()).hexdigest() != expected:
                    raise RuntimeError("NVDA checksum mismatch; refusing to stage this binary")
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise RuntimeError("Existing NVDA runtime does not match the pinned checksum")
        print("NVDA runtime checksum verified")
    rebuild()


if __name__ == "__main__":
    main()
