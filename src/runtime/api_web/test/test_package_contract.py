"""Runtime dependencies required by the split CORE API package."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT.parent / "gateway"
WEB_COMMON = ROOT.parents[1] / "hmi" / "web"
FLEET = ROOT.parents[1] / "site" / "fleet"


def test_api_and_core_declare_their_imported_web_runtime():
    api_package = (ROOT / "package.xml").read_text(encoding="utf-8")
    core_package = (CORE / "package.xml").read_text(encoding="utf-8")

    assert "<exec_depend>python3-fastapi</exec_depend>" in api_package
    assert "<exec_depend>python3-uvicorn</exec_depend>" in core_package


def test_web_common_is_an_installable_neutral_asset_package():
    manifest = (WEB_COMMON / "package.xml").read_text(encoding="utf-8")
    cmake = (WEB_COMMON / "CMakeLists.txt").read_text(encoding="utf-8")
    api_manifest = (ROOT / "package.xml").read_text(encoding="utf-8")
    fleet_manifest = (FLEET / "package.xml").read_text(encoding="utf-8")

    assert "<name>web_common</name>" in manifest
    assert "install(FILES" in cmake
    assert "tokens.css" in cmake and "components.css" in cmake
    assert "core_ui_logic.js" in cmake and "ui.js" in cmake
    assert "<exec_depend>web_common</exec_depend>" in api_manifest
    assert "<exec_depend>web_common</exec_depend>" in fleet_manifest
