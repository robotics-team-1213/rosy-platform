"""Fail the CORE image build if its installed imports or UI assets are incomplete."""

from pathlib import Path
from types import SimpleNamespace


def verify_assets(dashboard: Path, web_common: Path) -> None:
    for package, root, names in (
        ("dashboard", dashboard, ("index.html", "panels.yaml", "shell/shell.js")),
        ("web_common", web_common, ("tokens.css", "ui.js")),
    ):
        for name in names:
            asset = root / name
            if not asset.is_file() or asset.stat().st_size == 0:
                raise FileNotFoundError(f"{package}: missing installed asset {name}")


def main() -> None:
    # Import the same modules the CORE entry point and API need before ROS spins.
    import core.main  # noqa: F401
    import core.node  # noqa: F401
    from ament_index_python.packages import get_package_share_directory
    from core_api_web.api.app import _dashboard_root, _web_common_root, create_app

    dashboard = Path(get_package_share_directory("dashboard")).resolve()
    web_common = Path(get_package_share_directory("web_common")).resolve()
    verify_assets(dashboard, web_common)
    if _dashboard_root().resolve() != dashboard:
        raise RuntimeError("CORE dashboard resolved outside installed share")
    if _web_common_root().resolve() != web_common:
        raise RuntimeError("CORE web_common resolved outside installed share")

    app = create_app({}, SimpleNamespace())
    if not any(route.path == "/dashboard" for route in app.routes):
        raise RuntimeError("CORE dashboard route was not registered")


if __name__ == "__main__":
    main()
