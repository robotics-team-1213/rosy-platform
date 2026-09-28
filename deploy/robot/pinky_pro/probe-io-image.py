"""Fail the IO image build when control's installed web assets are absent."""

from pathlib import Path


def verify_web_common(installed_share: Path, selected_root: Path) -> None:
    for name in ("tokens.css", "components.css", "template.html", "core_ui_logic.js", "ui.js"):
        asset = installed_share / name
        if not asset.is_file() or asset.stat().st_size == 0:
            raise FileNotFoundError(f"web_common: missing installed asset {name}")
    if selected_root.resolve() != installed_share.resolve():
        raise RuntimeError("control web assets resolved outside installed share")


def main() -> None:
    from ament_index_python.packages import get_package_share_directory
    from control.web_http import web_common_dir

    get_package_share_directory("control")
    installed_share = Path(get_package_share_directory("web_common"))
    selected_root = Path(web_common_dir(str(installed_share)))
    verify_web_common(installed_share, selected_root)


if __name__ == "__main__":
    main()
