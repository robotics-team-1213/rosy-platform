"""D-466 — the header has three slots and the procedure column has one track.
D-741 6 — the Robot surface's screen switch and task list sit in the shared rail and sub-nav seats."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOKENS = ROOT / "shared" / "web" / "tokens.css"
CHOOSER = ROOT / "shared" / "web" / "task-chooser.js"
SHELL = ROOT / 'middleware' / 'robot_ui' / "robot" / "shell" / "shell.css"
FLEET = ROOT / 'applications' / 'fleet' / 'web' / "shared" / "styles.css"
# D-540 2: the four Fleet documents share one header sheet.
FLEET_HEADER = FLEET.with_name("fleet-header.css")


def test_sidebar_track_is_the_procedure_column():
    tokens = TOKENS.read_text(encoding="utf-8")
    assert "--sidebar-track: minmax(13rem, 18rem);" in tokens
    shell = SHELL.read_text(encoding="utf-8")
    fleet = FLEET.read_text(encoding="utf-8")
    # D-741 6: the Robot task list sits in the shared sub-nav seat, not in a column of its own.
    assert "--sidebar-track" not in shell and "procedure-tasks" not in shell
    robot = SHELL.parents[1]
    assert '<div class="ui-subnav"></div>' in (robot / "surface.html").read_text(encoding="utf-8")
    assert ".ui-subnav:empty { display: none; }" in shell, "a screen without tasks folds the empty seat"
    assert "subnav.append(taskChooser.element);" in (robot / "shell" / "mount.js").read_text(encoding="utf-8")
    assert "grid-template-columns: var(--sidebar-track) minmax(0, 1fr);" in fleet
    assert "minmax(13rem, 18rem)" not in shell
    assert "minmax(12rem, .22fr)" not in fleet
    assert 'rail.className = "ui-task-rail ui-sidebar"' in CHOOSER.read_text(encoding="utf-8")


def test_header_keeps_one_recipe_of_named_areas():
    shell = SHELL.read_text(encoding="utf-8")
    fleet = FLEET_HEADER.read_text(encoding="utf-8")
    # D-741 6: screen switching left the Robot header for the rail; the header is one row.
    assert 'grid-template-areas: "brand role estop";' in shell
    assert "grid-area: nav" not in shell and shell.count("grid-template-areas: \"brand") == 1
    # D-501/D-632: document links own their tab row; inbox and stop stay outside connection settings.
    # D-741 3·5: the Fleet app bar is one row at every width; it folds by its shell container.
    assert '"identity status actions safety"' in fleet
    assert '"identity safety" "status actions"' not in fleet
    assert fleet.count("grid-template-areas") == 1
    assert ".fleet-header-actions { grid-area: actions;" in fleet
