"""The private site map names every arm board once; the check reports what the host has beyond or short of it."""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/remote"))
import site_map  # noqa: E402

A, B, L = "2B162C9B50323952582E3120FF06202D", "7F31D1FE50323952582E3120FF061D2D", "D8F7C0C650323952582E3120FF053322"
HOST = {"arms": {"arm_a": {"follower": {"board": A}, "leader": {"board": L}}, "arm_b": {"follower": {"board": B}}}}


def test_findings_name_missing_and_unmapped_boards():
    assert site_map.board_findings(HOST, {A, B, L}) == []
    spare = "84C663DE50323952582E3120FF06132A"
    assert site_map.board_findings(HOST, {A, L, spare}) == [f"missing arm_b.follower board {B}", f"unmapped board {spare}"]


def test_a_board_mapped_twice_is_refused():
    with pytest.raises(SystemExit, match="mapped twice"):
        site_map.boards({"arms": {"arm_a": {"follower": {"board": A}}, "arm_b": {"leader": {"board": A}}}})


def test_load_requires_the_schema(tmp_path):
    path = tmp_path / "site-map.yaml"
    path.write_text(yaml.safe_dump({"schema": "rosy.site-map/1", "hosts": {"robttt": HOST}}), encoding="utf-8")
    assert site_map.load(path)["hosts"]["robttt"] == HOST
    path.write_text(yaml.safe_dump({"hosts": {}}), encoding="utf-8")
    with pytest.raises(SystemExit):
        site_map.load(path)


def test_the_openrb_pattern_reads_by_id_names():
    listing = f"usb-ROBOTIS_OpenRB-150_{A}-if00\nusb-Intel_RealSense-video-index0\n"
    assert set(site_map.OPENRB.findall(listing)) == {A}


# --- D-1021: time_source and apply-time -------------------------------------------------------------------

NTP, UP = "ntp.example.test", ["u1.example.test", "u2.example.test", "u3.example.test"]


def _site():
    return {"schema": site_map.SCHEMA, "time_source": {"client": NTP, "site": UP},
            "hosts": {"model": {"ssh": "op@model.example.test", "roles": ["model"]},
                      "r": {"ssh": "rosy-r (op@r.example.test, MagicDNS)", "roles": ["site"]},
                      "cell": {"ssh": "op@cell.example.test", "roles": ["omx"], "time_source": "Other.Example.Test."},
                      "bare": {"ssh": "op@bare.example.test"}},
            "robots": {"pinky_active": {"aaaa": "x"}}}


def test_the_time_source_is_the_hosts_own_else_the_one_for_its_role():
    site = _site()
    assert site_map.time_source(site, site["hosts"]["model"]) == {NTP}
    assert site_map.time_source(site, site["hosts"]["r"]) == set(UP)
    assert site_map.time_source(site, site["hosts"]["cell"]) == {"other.example.test"}
    assert site_map.time_source({"hosts": {}}, {"ssh": "x"}) is None
    for bad in ([], [""], 7, [3]):
        with pytest.raises(SystemExit, match="time_source"):
            site_map.time_source(site, {"time_source": bad})


def test_the_mismatch_text_names_both_sides_and_ignores_case_and_trailing_dots():
    assert site_map.time_mismatch({"ntp.example.test."}, {NTP}) is None
    text = site_map.time_mismatch({"gone.example.test"}, {NTP})
    assert "gone.example.test" in text and NTP in text
    assert "none" in site_map.time_mismatch(set(), {NTP})
    assert site_map.time_mismatch({NTP, "extra.example.test"}, {NTP}) is not None


def test_a_host_is_found_by_the_ssh_target_inside_its_map_text():
    site = _site()
    assert site_map.host_for(site, "op@r.example.test")[0] == "r"
    assert site_map.host_for(site, "op@model.example.test")[0] == "model"
    assert site_map.host_for(site, "op@nope.example.test") is None


class FakeSsh:
    """Records every remote command; chrony names and active units are per target."""

    def __init__(self, names=None, active=None, fail=()):
        self.names, self.active, self.fail, self.calls = names or {}, active or {}, fail, []

    def __call__(self, target, command, data=None):
        self.calls.append((target, command, data))
        if command == site_map.CHRONY_NAMES:
            return 0, self.names.get(target, "old.example.test\n")
        if "is-active" in command:
            return (0 if any(f"{u}.service" in command for u in self.active.get(target, ())) else 3), ""
        if "install" in command and target in self.fail:
            return 1, "boom"
        return 0, ""

    def changes(self):
        return [(t, c) for t, c, _ in self.calls if "sudo" in c or "cat >" in c or "rm -f" in c]


INSTALL = "sudo -n python3 /tmp/rosy_time_sync.py install --maintenance --role client --source ntp.example.test"


def test_a_dry_run_changes_nothing_and_says_what_it_would_do(capsys):
    ssh = FakeSsh()
    assert site_map.apply_time(_site(), ssh, execute=False, tool=b"T")
    assert ssh.changes() == []
    out = capsys.readouterr().out
    assert out.count("would run") == 4 and INSTALL in out  # model, cell is another source, bare, one robot
    assert "r: skipped" in out and "3 sources" in out


def test_execute_copies_the_tool_installs_and_removes_the_copy():
    ssh = FakeSsh()
    assert site_map.apply_time(_site(), ssh, execute=True, only="model", tool=b"TOOL")
    assert ssh.changes() == [("op@model.example.test", "umask 077 && cat > /tmp/rosy_time_sync.py"),
                             ("op@model.example.test", INSTALL), ("op@model.example.test", "rm -f /tmp/rosy_time_sync.py")]
    assert any(data == b"TOOL" for _, _, data in ssh.calls)


def test_a_host_whose_chrony_already_matches_is_skipped():
    ssh = FakeSsh(names={"op@model.example.test": f"{NTP}\n"})
    assert site_map.apply_time(_site(), ssh, execute=True, only="model", tool=b"T")
    assert ssh.changes() == []


def test_a_robot_with_workloads_running_is_refused_without_the_flag(capsys):
    ssh = FakeSsh(active={"rosy-pinky-aaaa": ("rosy-core", "rosy-navigation")})
    assert not site_map.apply_time(_site(), ssh, execute=True, only="rosy-pinky-aaaa", tool=b"T")
    assert ssh.changes() == []
    assert "refused" in capsys.readouterr().out


def test_robot_maintenance_stops_the_workloads_around_the_install_and_starts_them_again():
    ssh = FakeSsh(active={"rosy-pinky-aaaa": ("rosy-core", "rosy-io", "rosy-navigation")})
    assert site_map.apply_time(_site(), ssh, execute=True, only="rosy-pinky-aaaa", robot_maintenance=True, tool=b"T")
    assert [c for _, c in ssh.changes()] == [
        "sudo -n systemctl stop rosy-navigation.service", "sudo -n systemctl stop rosy-io.service",
        "sudo -n systemctl stop rosy-core.service", "umask 077 && cat > /tmp/rosy_time_sync.py", INSTALL,
        "rm -f /tmp/rosy_time_sync.py", "sudo -n systemctl start rosy-core.service",
        "sudo -n systemctl start rosy-io.service", "sudo -n systemctl start rosy-navigation.service"]


def test_the_robot_flag_does_not_let_a_host_with_workloads_running_be_changed():
    ssh = FakeSsh(active={"op@cell.example.test": ("rosy-core",)})
    assert not site_map.apply_time(_site(), ssh, execute=True, only="cell", robot_maintenance=True, tool=b"T")
    assert ssh.changes() == []


def test_a_failed_install_still_starts_the_stopped_workloads_and_fails_the_run(capsys):
    ssh = FakeSsh(active={"rosy-pinky-aaaa": ("rosy-core",)}, fail=("rosy-pinky-aaaa",))
    assert not site_map.apply_time(_site(), ssh, execute=True, only="rosy-pinky-aaaa", robot_maintenance=True, tool=b"T")
    assert ssh.changes()[-1][1] == "sudo -n systemctl start rosy-core.service"
    assert "FAIL install exit 1" in capsys.readouterr().out


def test_an_unknown_host_filter_is_a_failure(capsys):
    assert not site_map.apply_time(_site(), FakeSsh(), only="nope", tool=b"T")
    assert "no host matches" in capsys.readouterr().out


def test_the_command_line_is_a_dry_run_unless_told_to_execute(tmp_path, monkeypatch):
    path = tmp_path / "site-map.yaml"
    path.write_text(yaml.safe_dump(_site()), encoding="utf-8")
    monkeypatch.setenv("ROSY_SITE_MAP", str(path))
    seen = []
    monkeypatch.setattr(site_map, "apply_time", lambda site, **kw: seen.append(kw) or True)
    assert site_map.main(["apply-time"]) == 0 and seen[-1]["execute"] is False
    assert site_map.main(["apply-time", "--dry-run", "--host", "model"]) == 0 and seen[-1]["only"] == "model"
    assert site_map.main(["apply-time", "--execute", "--robot-maintenance"]) == 0
    assert seen[-1]["execute"] is True and seen[-1]["robot_maintenance"] is True
    monkeypatch.setattr(site_map, "apply_time", lambda site, **kw: False)
    assert site_map.main(["apply-time"]) == 1
