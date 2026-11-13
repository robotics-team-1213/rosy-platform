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

    def __init__(self, names=None, active=None, fail=(), state_exit=None, stop_exit=0):
        self.names, self.active, self.fail, self.calls = names or {}, active or {}, fail, []
        self.state_exit, self.stop_exit = state_exit, stop_exit

    def __call__(self, target, command, data=None):
        self.calls.append((target, command, data))
        if command == site_map.CHRONY_NAMES:
            return 0, self.names.get(target, "old.example.test\n")
        if command == "mktemp -d":
            return 0, f"{DIR}\n"
        if "is-active" in command:
            if self.state_exit is not None:
                return self.state_exit, ""
            return (0 if any(f"{u}.service" in command for u in self.active.get(target, ())) else 3), ""
        if "install" in command and target in self.fail:
            return 1, "boom"
        if "systemctl stop" in command:
            return self.stop_exit, ""
        return 0, ""

    def changes(self):
        return [(t, c) for t, c, _ in self.calls if "sudo" in c or "cat >" in c or "rm -rf" in c or "mktemp" in c]


DIR = "/tmp/tmp.Ab12Cd"
INSTALL = f"sudo -n python3 -I {DIR}/rosy_time_sync.py install --maintenance --role client --source ntp.example.test"
COPY = f"umask 077 && cat > {DIR}/rosy_time_sync.py"


def test_a_dry_run_changes_nothing_and_says_what_it_would_do(capsys):
    ssh = FakeSsh()
    assert site_map.apply_time(_site(), ssh, execute=False, tool=b"T")
    assert ssh.changes() == []
    out = capsys.readouterr().out
    assert out.count("would run") == 4 and INSTALL.replace(DIR, "<dir>") in out  # model, cell is another source, bare, one robot
    assert "r: skipped" in out and "never gets the client role" in out


def test_execute_copies_the_tool_installs_and_removes_the_copy():
    ssh = FakeSsh()
    assert site_map.apply_time(_site(), ssh, execute=True, only="model", tool=b"TOOL")
    assert ssh.changes() == [("op@model.example.test", "mktemp -d"), ("op@model.example.test", COPY),
                             ("op@model.example.test", INSTALL), ("op@model.example.test", f"rm -rf {DIR}")]
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


ROBOT = "rosy-pinky-aaaa"


def _maintain(ssh, **kw):
    kw = {"only": ROBOT, "robot_idle_confirmed": ROBOT, **kw}
    return site_map.apply_time(_site(), ssh, execute=True, robot_maintenance=True, tool=b"T", **kw)


def test_robot_maintenance_stops_the_workloads_around_the_install_and_starts_them_again(capsys):
    ssh = FakeSsh(active={ROBOT: ("rosy-core", "rosy-io", "rosy-navigation")})
    assert _maintain(ssh)
    assert [c for _, c in ssh.changes()] == [
        "mktemp -d", "sudo -n systemctl stop rosy-navigation.service", "sudo -n systemctl stop rosy-io.service",
        "sudo -n systemctl stop rosy-core.service", COPY, INSTALL, f"rm -rf {DIR}",
        "sudo -n systemctl start rosy-core.service", "sudo -n systemctl start rosy-io.service",
        "sudo -n systemctl start rosy-navigation.service"]
    assert capsys.readouterr().out.count("started") == 3


def test_robot_maintenance_needs_one_named_robot_that_a_person_confirmed_idle(capsys):
    ssh = FakeSsh(active={ROBOT: ("rosy-core",)})
    assert not _maintain(ssh, only=None)  # no --host: never every robot in a row
    assert not _maintain(ssh, only="cell")  # not a robot
    assert not _maintain(ssh, robot_idle_confirmed=None)
    assert not _maintain(ssh, robot_idle_confirmed="rosy-pinky-bbbb")  # another robot's name
    assert ssh.changes() == []
    out = capsys.readouterr().out
    assert "exactly one robot" in out and "--robot-idle-confirmed rosy-pinky-aaaa" in out


def test_a_failed_install_still_starts_the_stopped_workloads_and_fails_the_run(capsys):
    ssh = FakeSsh(active={ROBOT: ("rosy-core",)}, fail=(ROBOT,))
    assert not _maintain(ssh)
    assert ssh.changes()[-1][1] == "sudo -n systemctl start rosy-core.service"
    assert "FAIL install exit 1" in capsys.readouterr().out


def test_a_stop_that_times_out_is_still_followed_by_a_start_of_every_unit_tried(capsys):
    ssh = FakeSsh(active={ROBOT: ("rosy-core", "rosy-navigation")}, stop_exit=255)
    assert not _maintain(ssh)
    commands = [c for _, c in ssh.changes()]
    assert "sudo -n systemctl start rosy-navigation.service" in commands[-1:]
    assert commands.count("sudo -n systemctl start rosy-navigation.service") == 1
    assert not any(INSTALL == c for c in commands)  # nothing installed after a failed stop
    assert "FAIL could not stop rosy-navigation" in capsys.readouterr().out


def test_a_start_that_fails_after_the_install_is_reported_loudly(capsys):
    class NoStart(FakeSsh):
        def __call__(self, target, command, data=None):
            return (1, "") if "systemctl start" in command else super().__call__(target, command, data)

    assert not _maintain(NoStart(active={ROBOT: ("rosy-core",)}))
    assert "FAIL could not start rosy-core; start it by hand now" in capsys.readouterr().out


def test_a_site_role_host_never_gets_the_client_role_even_with_one_upstream(capsys):
    for own in (None, "only.example.test"):  # the map's one upstream, or the host's own single source
        full = _site()
        full["time_source"]["site"] = "only.example.test"
        if own:
            full["hosts"]["r"]["time_source"] = own
        ssh = FakeSsh()
        assert site_map.apply_time(full, ssh, execute=True, only="r", tool=b"T")
        assert ssh.changes() == [] and "never gets the client role" in capsys.readouterr().out


@pytest.mark.parametrize("exit_code", [255, 4, 1])
def test_an_unknown_workload_state_refuses_the_host(capsys, exit_code):
    ssh = FakeSsh(state_exit=exit_code)
    assert not site_map.apply_time(_site(), ssh, execute=True, only="model", tool=b"T")
    assert ssh.changes() == []
    assert "FAIL cannot tell whether" in capsys.readouterr().out


def test_chrony_names_ignore_trailing_dots_in_what_the_host_prints():
    ssh = FakeSsh(names={"op@model.example.test": f"{NTP}.\n"})
    assert site_map.apply_time(_site(), ssh, execute=True, only="model", tool=b"T")
    assert ssh.changes() == []


def test_ssh_stderr_never_mixes_into_the_chrony_names(monkeypatch):
    class Done:
        returncode, stdout, stderr = 0, f"{NTP}\n".encode(), b"Warning: Permanently added a host key\n"

    monkeypatch.setattr(site_map.subprocess, "run", lambda *a, **k: Done())
    assert site_map.ssh_run("t", "x") == (0, f"{NTP}\n")
    Done.returncode = 255
    assert "Warning" in site_map.ssh_run("t", "x")[1]  # kept for the failure line


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
    assert site_map.main(["apply-time", "--execute", "--robot-maintenance", "--robot-idle-confirmed", ROBOT]) == 0
    assert seen[-1]["execute"] is True and seen[-1]["robot_maintenance"] is True
    assert seen[-1]["robot_idle_confirmed"] == ROBOT
    monkeypatch.setattr(site_map, "apply_time", lambda site, **kw: False)
    assert site_map.main(["apply-time"]) == 1
