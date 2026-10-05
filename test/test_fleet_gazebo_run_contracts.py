"""D-426 Task 1 — 실행 격리·예약·manifest 계약 (host, ROS-free).

실패 시험이 먼저다(계획 공통 규칙 5). 이 파일이 고정하는 것:

- 두 run의 포트/domain/namespace 충돌 판정
- run root 재사용 거부(살아 있는 manifest·오래된 manifest 모두)
- run root 밖으로 빠지는 symlink 거부
- world/map/profile 파일 hash 누락 거부
- overlay의 fleet.hub_url·pairing_token 과 fleet manifest 불일치 거부
- 관측 probes에 하나라도 불명이면 READY 불가
- run.py --help·실패 exit code
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools" / "validation" / "fleet_gazebo"
sys.path.insert(0, str(TOOLS))

from preflight import (  # noqa: E402
    MANIFEST_NAME,
    PreflightError,
    Reservations,
    check_no_symlink_escape,
    check_overlays,
    port_conflicts,
    readiness,
    require_file_hashes,
    validate_run_root,
    write_manifest,
)

import run as run_cli  # noqa: E402


def _parts():
    import importlib.util
    path = TOOLS.parents[2] / "integrations/simulation/gazebo/launch/gz_multi_parts.py"
    spec = importlib.util.spec_from_file_location("sim_parts", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_launch_spec_requires_valid_domain_and_matching_robot_namespaces(tmp_path):
    import yaml
    parts = _parts()
    spec = {"run_id": "d426-unit", "core_config_dir": str(tmp_path),
            "fleet_manifest": str(tmp_path / "robots.yaml"), "hub_url": "http://127.0.0.1:32001",
            "gz_partition": "d426-unit", "ros_domain_id": 150,
            "robots": [{"namespace": "rosy_01", "api_port": 31001}]}
    path = tmp_path / "run_spec.yaml"
    for domain in (None, True, "150", 119, 200):
        path.write_text(yaml.safe_dump({**spec, "ros_domain_id": domain}), encoding="utf-8")
        with pytest.raises(RuntimeError, match="domain"):
            parts.load_run_spec(str(path))
    path.write_text(yaml.safe_dump(spec), encoding="utf-8")
    loaded = parts.load_run_spec(str(path))
    parts.validate_run_identity(loaded, 1, "rosy")
    for robots, prefix in ((2, "rosy"), (1, "other")):
        with pytest.raises(RuntimeError, match="namespace"):
            parts.validate_run_identity(loaded, robots, prefix)


def test_domain_action_precedes_every_launch_participant():
    import ast
    path = TOOLS.parents[2] / "integrations/simulation/gazebo/launch/gz_multi.launch.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    setup = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_launch_setup")
    calls = [n for n in ast.walk(setup) if isinstance(n, ast.Call)]
    domain = next(n for n in calls if isinstance(n.func, ast.Name) and
                  n.func.id == "SetEnvironmentVariable" and n.args and
                  isinstance(n.args[0], ast.Constant) and n.args[0].value == "ROS_DOMAIN_ID")
    participants = [n.lineno for n in calls if isinstance(n.func, ast.Name) and
                    n.func.id in {"Node", "IncludeLaunchDescription", "ExecuteProcess"}]
    assert participants and domain.lineno < min(participants)


def test_runner_refuses_existing_domain_reservation_before_writing(tmp_path):
    old = _reservations()
    write_manifest(tmp_path / "old", old, versions={}, hashes={}, argv=[])
    with pytest.raises(PreflightError, match="conflict"):
        run_cli.check_reservations(tmp_path, old)


@pytest.mark.parametrize("field,value", [("ros_domain_id", "150"), ("robots", True),
                                         ("api_ports", []), ("namespaces", ["other_01"])])
def test_runner_refuses_corrupted_recorded_reservations(tmp_path, field, value):
    path = write_manifest(tmp_path / "old", _reservations(), versions={}, hashes={}, argv=[])
    data = json.loads(path.read_text(encoding="utf-8"))
    data["reservations"][field] = value
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(PreflightError, match="invalid reservation"):
        run_cli.check_reservations(tmp_path, _reservations("d426-unit-2"))


def test_manifest_claim_cannot_overwrite_a_concurrent_single_use_run(tmp_path, monkeypatch):
    import preflight
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    rendezvous = Barrier(2)
    original = preflight.validate_run_root
    def checked(root):
        original(root)
        rendezvous.wait(timeout=3)
    monkeypatch.setattr(preflight, "validate_run_root", checked)
    def claim(marker):
        try:
            write_manifest(tmp_path / "run", _reservations(), versions={"claim": marker},
                           hashes={}, argv=[])
            return marker
        except PreflightError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ("first", "second")))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert json.loads((tmp_path / "run" / MANIFEST_NAME).read_text(encoding="utf-8"))["versions"] == {
        "claim": winners[0]}


@pytest.mark.parametrize("role", ["api", "console"])
def test_runner_refuses_an_occupied_reserved_listener(tmp_path, role):
    import socket
    from dataclasses import replace
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        reserved = replace(_reservations(), **({"console_port": port} if role == "console" else
                                               {"api_ports": (port,)}))
        with pytest.raises(PreflightError, match="port"):
            run_cli.check_reservations(tmp_path, reserved)


def _reservations(run_id="d426-unit", robots=2, started=1_700_000_000.0):
    return Reservations.derive(run_id, robots, started_at=started)


def test_two_runs_that_reserve_the_same_port_are_a_conflict():
    first = _reservations()
    same = Reservations.derive(first.run_id, first.robots, started_at=first.started_at)
    other = _reservations(run_id="d426-unit-2")
    assert port_conflicts(first, same) is True
    assert port_conflicts(first, other) is False


def test_namespaces_and_ports_are_per_robot_and_distinct():
    res = _reservations(robots=2)
    assert res.namespaces == ("rosy_01", "rosy_02")
    assert len(set(res.api_ports)) == res.robots
    assert len(res.gz_partition) >= 8 and res.run_id in res.gz_partition


def test_run_root_reuse_with_any_existing_manifest_is_refused(tmp_path):
    root = tmp_path / "run-1"
    root.mkdir()
    (root / MANIFEST_NAME).write_text(json.dumps({"run_id": "old"}), encoding="utf-8")
    with pytest.raises(PreflightError, match="manifest"):
        validate_run_root(root)


def test_run_root_that_is_a_symlink_is_refused(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link-run"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError as exc:  # Windows without developer mode cannot mint symlinks
        pytest.skip(f"symlink creation unavailable here: {exc}")
    with pytest.raises(PreflightError, match="symlink"):
        validate_run_root(link)


def test_symlink_escaping_the_run_root_is_refused(tmp_path):
    root = tmp_path / "run"
    (root / "evidence").mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    try:
        (root / "evidence" / "escape").symlink_to(outside)
    except OSError as exc:  # Windows without developer mode cannot mint symlinks
        pytest.skip(f"symlink creation unavailable here: {exc}")
    with pytest.raises(PreflightError, match="escape"):
        check_no_symlink_escape(root)


def test_missing_world_map_or_profile_hash_is_refused(tmp_path):
    world = tmp_path / "course.world"
    world.write_text("<sdf/>", encoding="utf-8")
    with pytest.raises(PreflightError, match="map"):
        require_file_hashes({"world": world, "map": tmp_path / "missing.yaml"})
    hashes = require_file_hashes({"world": world})
    assert set(hashes) == {"world"} and len(hashes["world"]) == 64


def test_manifest_binds_run_id_start_time_versions_and_hashes(tmp_path):
    root = tmp_path / "run-a"
    res = _reservations()
    path = write_manifest(root, res, versions={"ros": "jazzy", "gz": "harmonic"},
                          hashes={"world": "a" * 64}, argv=["run.py", "--robots", "2"])
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["run_id"] == res.run_id
    assert data["started_at"] == res.started_at
    assert data["reservations"]["ros_domain_id"] == res.ros_domain_id
    assert data["versions"] == {"ros": "jazzy", "gz": "harmonic"}
    assert data["hashes"]["world"] == "a" * 64
    assert data["argv"] == ["run.py", "--robots", "2"]


def test_overlays_must_match_the_fleet_manifest_tokens(tmp_path):
    root = tmp_path / "run-b"
    root.mkdir()
    hub = "http://127.0.0.1:32010"
    overlay = root / "core_rosy_01.yaml"
    overlay.write_text(
        f"fleet:\n  hub_url: {hub}\n  pairing_token: deadbeef\n", encoding="utf-8")
    manifest = {"robots": [{"robot_id": "rosy_01", "fleet_pairing_token": "deadbeef"}]}
    check_overlays(root, ("rosy_01",), hub, manifest)  # 일치 → 통과
    with pytest.raises(PreflightError, match="rosy_02"):
        check_overlays(root, ("rosy_01", "rosy_02"), hub, manifest)
    manifest_drift = {"robots": [{"robot_id": "rosy_01", "fleet_pairing_token": "other"}]}
    with pytest.raises(PreflightError, match="pairing"):
        check_overlays(root, ("rosy_01",), hub, manifest_drift)


REQUIRED_PROBES = ("clock", "scan", "odom", "tf", "nav2", "core_http", "ws_welcome")


def test_readiness_requires_every_probe_true_and_reports_unknowns():
    good = {name: True for name in REQUIRED_PROBES}
    assert readiness(good) == (True, [])
    unknown = {**good, "ws_welcome": None}
    ready, why = readiness(unknown)
    assert ready is False and any("ws_welcome" in item for item in why)
    ready, why = readiness({})  # 전부 불명
    assert ready is False and len(why) == len(REQUIRED_PROBES)


def test_cli_help_is_a_working_command():
    result = subprocess.run([sys.executable, str(TOOLS / "run.py"), "--help"],
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0
    for flag in ("--robots", "--scenario", "--output-root", "--run-id"):
        assert flag in result.stdout


def test_cli_refuses_missing_world_and_map_and_exits_nonzero(tmp_path):
    output = tmp_path / "runs"
    result = subprocess.run(
        [sys.executable, str(TOOLS / "run.py"), "--robots", "2",
         "--output-root", str(output), "--run-id", "d426-cli",
         "--world", str(tmp_path / "nope.world"), "--map", str(tmp_path / "nope.yaml"),
         "--profile", str(tmp_path / "nope_profile.yaml")],
        capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 2
    assert "world" in (result.stdout + result.stderr)


def test_cli_generates_matching_overlays_and_manifest(tmp_path, capsys):
    world = tmp_path / "course.world"; world.write_text("<sdf/>", encoding="utf-8")
    map_yaml = tmp_path / "course.yaml"; map_yaml.write_text("image: x.png", encoding="utf-8")
    profile = tmp_path / "profile.yaml"; profile.write_text("robot: {}", encoding="utf-8")
    output = tmp_path / "runs"
    result = run_cli.main(["--robots", "2", "--scenario", "all", "--output-root", str(output),
                           "--run-id", "d426-gen", "--world", str(world), "--map", str(map_yaml),
                           "--profile", str(profile)])
    assert result == 0
    output_text = capsys.readouterr().out
    root = output / "d426-gen"
    import yaml
    manifest = json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
    domain_env = f"env ROS_DOMAIN_ID={manifest['reservations']['ros_domain_id']} "
    assert f"gz launch:  {domain_env}" in output_text
    assert f"fleet:      {domain_env}" in output_text
    assert manifest["hashes"]["world"] and manifest["hashes"]["map"]
    robots_yaml = yaml.safe_load((root / "robots.yaml").read_text(encoding="utf-8"))
    overlays = {}
    for row in robots_yaml["robots"]:
        overlay = yaml.safe_load((root / f"core_{row['robot_id']}.yaml").read_text(encoding="utf-8"))
        overlays[row["robot_id"]] = overlay
        assert overlay["fleet"]["hub_url"] == manifest["reservations"]["hub_url"]
        assert overlay["fleet"]["pairing_token"] == row["fleet_pairing_token"]
        assert row["base_url"].startswith("http://127.0.0.1:")
    ports = [item["network"]["api_port"] for item in overlays.values()]
    assert len(set(ports)) == len(robots_yaml["robots"])
    # 재실행은 같은 run_id로 거부된다(오래된/살아 있는 manifest 구분 없이 새 run_id 필요).
    rerun = run_cli.main(["--robots", "2", "--scenario", "all", "--output-root", str(output),
                          "--run-id", "d426-gen", "--world", str(world), "--map", str(map_yaml),
                          "--profile", str(profile)])
    assert rerun == 2
