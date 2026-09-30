"""manifest.json is the one /common allowlist for core, fleet, games and control.

Each server reads it instead of keeping its own list, so a shared file that is
installed but missing here would 404 on some servers and not others.
"""

import json
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((WEB / "manifest.json").read_text(encoding="utf-8"))
ASSETS = MANIFEST["shared_assets"]
#: Installed next to the assets but not served under /common.
NOT_SHARED = {"manifest.json"}


def _installed_files() -> set[str]:
    """Share-relative paths from every install(FILES ...) block."""
    text = (WEB / "CMakeLists.txt").read_text(encoding="utf-8")
    blocks = re.findall(r"install\(FILES(.*?)DESTINATION\s+share/\$\{PROJECT_NAME\}(\S*)\s*\)", text, re.S)
    assert blocks, "CMakeLists.txt no longer has an install(FILES ...) block"
    installed = set()
    for files, subdir in blocks:
        for name in files.split():
            # install(FILES) keeps the basename; the DESTINATION suffix is the served folder.
            installed.add((subdir.strip("/") + "/" if subdir else "") + name.rsplit("/", 1)[-1])
    return installed


def test_every_manifest_asset_exists_as_a_plain_file():
    for name in ASSETS:
        # One level only: D-370 surface icons live in icons/, each listed by name.
        folder, _, base = name.rpartition("/")
        assert folder in ("", "icons") and base and not base.startswith("."), name
        assert ".." not in name and "\\" not in name, name
        assert (WEB / name).is_file(), f"manifest names a missing file: {name}"


def test_manifest_and_install_list_agree():
    installed = _installed_files()
    assert "manifest.json" in installed, "servers read share/web_common/manifest.json"
    assert installed - NOT_SHARED == set(ASSETS), (
        f"installed but not shared: {sorted(installed - NOT_SHARED - set(ASSETS))}; "
        f"shared but not installed: {sorted(set(ASSETS) - installed)}")


def test_media_types_are_canonical():
    allowed = {".css": "text/css", ".html": "text/html", ".js": "text/javascript",
               ".svg": "image/svg+xml"}
    for name, media in ASSETS.items():
        assert media == allowed[Path(name).suffix], (name, media)


def test_hold_ticker_is_shared():
    assert "hold-ticker.js" in ASSETS
