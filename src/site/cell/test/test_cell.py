from pathlib import Path

import pytest

from rosy_cell.cell import CellError, load_cell

FIXTURE = Path(__file__).parent / "fixtures" / "cell_demo.yaml"


def test_fixture_builds_frames_and_stations():
    cell = load_cell(FIXTURE.read_text(encoding="utf-8"))
    assert cell.frames["pallet_a"].to_base((0.0, 0.0, 0.0)) == pytest.approx((0.2, 0.0, 0.0))
    assert cell.station_pose("infeed") == pytest.approx((0.0, 0.2, 0.02, 0.0))
    assert cell.approach_clearance_m == 0.05
    assert len(cell.content_hash) == 64


@pytest.mark.parametrize(
    "old, new, problem",
    [
        ("rosy_cell.cell/2", "rosy_cell.cell/9", "schema"),
        ("rosy_cell.cell/2", "rosy_cell.cell/1", "schema"),  # /1 is never silently upgraded
        ("home: {x: 0.1, y: 0.0, z: 0.15, yaw: 0.0}\n", "", "home"),
        ("kinematics_revision: fixture-urdf-1\n", "", "kinematics_revision"),
        ("kinematics_revision: fixture-urdf-1", "kinematics_revision: ''", "kinematics_revision"),
        ("kinematics_revision: fixture-urdf-1", "kinematics_revision: 7", "kinematics_revision"),
        ("kinematics_revision: fixture-urdf-1", "kinematics_revision: ' fixture-urdf-1'", "kinematics_revision"),
        ("kinematics_revision: fixture-urdf-1", "kinematics_revision: 'fixture-urdf-1 '", "kinematics_revision"),
        ("home: {x: 0.1,", "home: {x: .nan,", "home.x"),
        ("home: {x: 0.1, y: 0.0, z: 0.15", "home: {x: 0.1, y: 0.0, z: .inf", "home.z"),
        ("z: 0.15, yaw: 0.0}", "z: 0.15, yaw: '0'}", "home.yaw"),
        ("home: {x: 0.1,", "home: {frame: base, x: 0.1,", "home.frame"),
        ("home: {x: 0.1, y: 0.0, ", "home: {x: 0.1, ", "home.y"),
        ("plane_point: [0.2, 0.1, 0]", "plane_point: [0.2, 0.1, 0.05]", "tilt"),
        ("x_point: [0.3, 0, 0]", "x_point: [0.205, 0, 0]", "pallet_a"),
        ("{frame: base, x: 0.0", "{frame: nowhere, x: 0.0", "unknown frame"),
        ("approach_clearance_m: 0.05", "approach_clearance_m: 0", "approach_clearance_m"),
        # non-finite and wrong-typed numbers
        ("approach_clearance_m: 0.05", "approach_clearance_m: .nan", "approach_clearance_m"),
        ("approach_clearance_m: 0.05", "approach_clearance_m: .inf", "approach_clearance_m"),
        ("approach_clearance_m: 0.05", "approach_clearance_m: '0.05'", "approach_clearance_m"),
        pytest.param(
            "approach_clearance_m: 0.05",
            "approach_clearance_m: 1" + "0" * 400,
            "approach_clearance_m",
            id="clearance-int-too-large-for-float",
        ),
        ("min_angle_deg: 10.0", "min_angle_deg: 0", "frame_rules.min_angle_deg"),
        ("max_tilt_deg: 5.0", "max_tilt_deg: .nan", "frame_rules.max_tilt_deg"),
        ("min_span_m: 0.02", "min_span_m: 0", "frame_rules.min_span_m"),
        ("min_angle_deg: 10.0", "min_angle_deg: .inf", "frame_rules.min_angle_deg"),
        ("min_angle_deg: 10.0", "min_angle_deg: true", "frame_rules.min_angle_deg"),
        ("origin: [0.2, 0, 0]", "origin: [.nan, 0, 0]", "pallet_a"),
        ("origin: [0.2, 0, 0]", "origin: ['0.2', 0, 0]", "frames.pallet_a.origin"),
        ("x: 0.0, y: 0.2", "x: '0.0', y: 0.2", "stations.infeed.x"),
        ("x: 0.0, y: 0.2", "x: .nan, y: 0.2", "stations.infeed.x"),
        ("yaw: 0.0}", "yaw: .inf}", "stations.infeed.yaw"),
        ("yaw: 0.0}", "yaw: no}", "stations.infeed.yaw"),
        # malformed containers, keys and ids
        ("origin: [0, 0, 0]", "origin: [0, 0]", "frames.base.origin"),
        ("origin: [0, 0, 0]", "origin: 0", "frames.base.origin"),
        ("base: {origin: [0, 0, 0], x_point: [0.1, 0, 0], plane_point: [0, 0.1, 0]}", "base: [0, 0, 0]", "frames.base"),
        ("  base: {", "  1: {", "frames"),
        ("{frame: base, x: 0.0", "{frame: [base], x: 0.0", "stations.infeed.frame"),
        ("{frame: base, x: 0.0", "{frame: base, colour: red, x: 0.0", "stations.infeed.colour"),
        ("frame_rules: {min_span_m: 0.02, min_angle_deg: 10.0, max_tilt_deg: 5.0}", "frame_rules: [0.02]", "frame_rules"),
        ("stations:\n", "stations: 3\nold_stations:\n", "stations"),
        ("approach_clearance_m: 0.05", "approach_clearance_m: 0.05\ntaught_on: 2026-10-01", "taught_on"),
    ],
)
def test_bad_cells_name_the_problem(old, new, problem):
    text = FIXTURE.read_text(encoding="utf-8").replace(old, new, 1)
    with pytest.raises(CellError) as err:
        load_cell(text)
    assert any(problem in p for p in err.value.problems), err.value.problems


def test_empty_frames_is_a_cell_error():
    text = FIXTURE.read_text(encoding="utf-8")
    head, rest = text.split("frames:\n", 1)
    tail = rest[rest.index("stations:") :]
    with pytest.raises(CellError) as err:
        load_cell(head + "frames:\n" + tail)
    assert any("frames" in p for p in err.value.problems), err.value.problems


@pytest.mark.parametrize("text", ["", "- a list", "a: [unclosed", "just text"])
def test_non_mapping_or_unparsable_text_is_a_cell_error(text):
    with pytest.raises(CellError):
        load_cell(text)


def test_frames_and_stations_are_read_only():
    cell = load_cell(FIXTURE.read_text(encoding="utf-8"))
    with pytest.raises(TypeError):
        cell.frames["pallet_a"] = cell.frames["base"]
    with pytest.raises(TypeError):
        cell.stations["infeed"] = cell.stations["sheets"]


def test_zero_max_tilt_is_allowed():
    # the fixture frames are taught flat (tilt 0), so a zero tilt budget still loads
    cell = load_cell(FIXTURE.read_text(encoding="utf-8").replace("max_tilt_deg: 5.0", "max_tilt_deg: 0", 1))
    assert cell.frames["pallet_a"].tilt_deg() == pytest.approx(0.0)


def test_home_and_kinematics_revision_are_exposed():
    cell = load_cell(FIXTURE.read_text(encoding="utf-8"))
    assert (cell.home.x, cell.home.y, cell.home.z, cell.home.yaw) == (0.1, 0.0, 0.15, 0.0)
    assert cell.kinematics_revision == "fixture-urdf-1"
    with pytest.raises(AttributeError):
        cell.home.z = 0.2


@pytest.mark.parametrize(
    "old, new",
    [("x: 0.1, y: 0.0, z: 0.15", "x: 0.1, y: 0.0, z: 0.16"), ("fixture-urdf-1", "fixture-urdf-2")],
)
def test_hash_changes_with_home_and_kinematics_revision(old, new):
    text = FIXTURE.read_text(encoding="utf-8")
    assert load_cell(text).content_hash != load_cell(text.replace(old, new, 1)).content_hash
