"""D-466 — the header has three slots and the procedure column has one track."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "shared" / "web" / "tokens.css"
CHOOSER = ROOT / "shared" / "web" / "task-chooser.js"
SHELL = ROOT / "middleware" / "ui" / "robot" / "shell" / "shell.css"
FLEET = ROOT / "operations" / "fleet" / "fleet" / "server" / "web" / "styles.css"


def test_sidebar_track_is_the_procedure_column():
    tokens = TOKENS.read_text(encoding="utf-8")
    assert "--sidebar-track: minmax(13rem, 18rem);" in tokens
    shell = SHELL.read_text(encoding="utf-8")
    fleet = FLEET.read_text(encoding="utf-8")
    assert "grid-template-columns: var(--sidebar-track) minmax(0, 1fr);" in shell
    assert "grid-template-columns: var(--sidebar-track) minmax(0, 1fr);" in fleet
    assert "minmax(13rem, 18rem)" not in shell
    assert "minmax(12rem, .22fr)" not in fleet
    assert 'rail.className = "ui-task-rail ui-sidebar"' in CHOOSER.read_text(encoding="utf-8")


def test_header_keeps_one_recipe_of_named_areas():
    shell = SHELL.read_text(encoding="utf-8")
    fleet = FLEET.read_text(encoding="utf-8")
    assert '"brand role estop" "nav nav estop"' in shell
    assert '"brand pill cell clock more estop"' in fleet
    assert '"brand cell more estop" "pill clock clock estop"' in fleet
