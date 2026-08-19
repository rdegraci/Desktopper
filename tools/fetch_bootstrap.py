"""Download Bootstrap 5.3.3 once into static/. urllib only. No npm."""

from __future__ import annotations

import hashlib
import io
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

VERSION = "5.3.3"
ZIP_URL = (
    "https://github.com/twbs/bootstrap/releases/download/"
    f"v{VERSION}/bootstrap-{VERSION}-dist.zip"
)
ZIP_SHA256 = "5b0a245ab8458951668d29fd149fc6c8e63c676977efc23822a223c08245de1a"

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC = REPO_ROOT / "static"
CSS_NAME = "bootstrap.min.css"
JS_NAME = "bootstrap.bundle.min.js"
MAP_CSS = "bootstrap.min.css.map"
MAP_JS = "bootstrap.bundle.min.js.map"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _find_member(names: list[str], filename: str) -> str | None:
    suffix = "/" + filename
    for name in names:
        if name.endswith(suffix) or name == filename:
            if name.endswith("/"):
                continue
            return name
    return None


def main() -> int:
    print(f"Downloading {ZIP_URL}", flush=True)
    try:
        with urllib.request.urlopen(ZIP_URL, timeout=120) as resp:
            blob = resp.read()
    except OSError as exc:
        print(f"Download failed: {exc}", file=sys.stderr)
        return 1

    digest = _sha256(blob)
    tmp_zip = Path(tempfile.gettempdir()) / f"bootstrap-{VERSION}-dist.zip"
    tmp_zip.write_bytes(blob)

    if not ZIP_SHA256:
        print("No pinned SHA256 in this script. Computed digest:")
        print(digest)
        print("Set ZIP_SHA256 to that value and run again.")
        tmp_zip.unlink(missing_ok=True)
        return 1

    if digest != ZIP_SHA256:
        tmp_zip.unlink(missing_ok=True)
        print(
            f"SHA256 mismatch. expected {ZIP_SHA256} got {digest}. Zip deleted.",
            file=sys.stderr,
        )
        return 1

    css_dir = STATIC / "css"
    js_dir = STATIC / "js"
    css_dir.mkdir(parents=True, exist_ok=True)
    js_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = zf.namelist()
        mapping = {
            CSS_NAME: css_dir / CSS_NAME,
            JS_NAME: js_dir / JS_NAME,
            MAP_CSS: css_dir / MAP_CSS,
            MAP_JS: js_dir / MAP_JS,
        }
        required = (CSS_NAME, JS_NAME)
        for filename, dest in mapping.items():
            member = _find_member(names, filename)
            if member is None:
                if filename in required:
                    print(f"Zip is missing {filename}", file=sys.stderr)
                    return 1
                continue
            dest.write_bytes(zf.read(member))
            print(f"Wrote {dest.relative_to(REPO_ROOT)}")

    tmp_zip.unlink(missing_ok=True)
    print("Bootstrap 5.3.3 is in static/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
