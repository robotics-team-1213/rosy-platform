"""omx_incident: an arm session that ends in trouble is collected, decided by measurement, recorded as a decision
row, recovered only by an allowed reboot and reported to Fleet, which holds the arm for a person (arm_b 2026-11-03 13:27;
D-971). Fleet is a fake link here: its own routes are tested in operations/fleet/test/test_arm_incidents.py."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "deploy/robot/omx"))
import omx_incident as oi  # noqa: E402
from core_common.protocol.arm_incident.arm_incidents import ArmIncidentAccepted as Accepted, ArmIncidentHold as Hold  # noqa: E402

SID = "6f1c2a3e-1b2d-4e5f-8a9b-0c1d2e3f4a5b"
HOME = [0.8, -62.2, 51.8, 51.4, 45.0, 54.4]


@pytest.fixture(autouse=True)
def isolated_arm_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSY_OMX_HOME", str(tmp_path / "arm-home"))


def test_hold_survives_a_new_recording_directory(tmp_path, monkeypatch):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    monkeypatch.chdir(first)
    oi.handle(session(first), "arm_b")
    monkeypatch.chdir(second)
    with pytest.raises(SystemExit, match="held for a person"):
        oi.refuse_if_held("arm_b")
    oi.refuse_if_held("arm_a")


def test_hold_is_durable_before_recovery_callback_can_fail(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def broken(ids):
        raise RuntimeError("recovery unavailable")

    with pytest.raises(RuntimeError, match="recovery unavailable"):
        oi.handle(session(tmp_path), "arm_b", act=broken)
    with pytest.raises(SystemExit, match="held for a person"):
        oi.refuse_if_held("arm_b")


def test_cli_handle_refuses_while_the_arm_session_is_owned(tmp_path, monkeypatch):
    import joint_tune

    monkeypatch.chdir(tmp_path)
    oi.handle(session(tmp_path), "arm_b")

    def busy(arm):
        raise SystemExit("another OMX session owns this arm")

    monkeypatch.setattr(joint_tune, "session_lock", busy)
    with pytest.raises(SystemExit, match="another OMX session"):
        oi.main(["handle", "--session", str(tmp_path / "session.json"), "--arm", "arm_b"])
    assert oi.held("arm_b")


@pytest.mark.parametrize("bad_read", ["transport", "packet"])
def test_reboot_refuses_failed_torque_readback(tmp_path, monkeypatch, bad_read):
    from types import SimpleNamespace

    rebooted, closed = [], []
    port = SimpleNamespace(openPort=lambda: True, setBaudRate=lambda baud: True,
                           closePort=lambda: closed.append(True))

    def read(bus, motor, address):
        if motor == 13 and address == 64:
            return (0, -3001, 0) if bad_read == "transport" else (0, 0, 1)
        return (32 if address == 70 and motor == 13 else 0, 0, 0)

    packet = SimpleNamespace(read1ByteTxRx=read,
                             reboot=lambda bus, motor: rebooted.append(motor) or (0, 0))
    monkeypatch.setitem(sys.modules, "dynamixel_sdk", SimpleNamespace(
        COMM_SUCCESS=0, PortHandler=lambda device: port, PacketHandler=lambda version: packet))
    monkeypatch.setattr(oi.time, "sleep", lambda seconds: None)
    result = oi.reboot_latched("fake-follower")([13])
    assert rebooted == []
    assert result.get("error") or result.get("refused")
    assert closed == [True]


@pytest.mark.parametrize("failure", [None, "ack-transport", "ack-packet", "after-transport",
                                    "after-packet", "torque-on", "still-latched"])
def test_reboot_requires_valid_ack_and_clean_readback(monkeypatch, failure):
    from types import SimpleNamespace

    rebooted, closed = [], []
    port = SimpleNamespace(openPort=lambda: True, setBaudRate=lambda baud: True,
                           closePort=lambda: closed.append(True))

    def read(bus, motor, address):
        if rebooted and motor == 13:
            if failure == "after-transport":
                return 0, -3001, 0
            if failure == "after-packet":
                return 0, 0, 1
            if failure == "torque-on" and address == 64:
                return 1, 0, 0
        fault = motor == 13 and address == 70 and (not rebooted or failure == "still-latched")
        return (32 if fault else 0), 0, (128 if fault else 0)

    def reboot(bus, motor):
        rebooted.append(motor)
        return (-3001 if failure == "ack-transport" else 0), (1 if failure == "ack-packet" else 0)

    packet = SimpleNamespace(read1ByteTxRx=read, reboot=reboot)
    monkeypatch.setitem(sys.modules, "dynamixel_sdk", SimpleNamespace(
        COMM_SUCCESS=0, PortHandler=lambda device: port, PacketHandler=lambda version: packet))
    monkeypatch.setattr(oi.time, "sleep", lambda seconds: None)
    result = oi.reboot_latched("fake-follower")([13])
    assert closed == [True]
    if failure is None:
        assert result["rebooted"] == [13]
    else:
        assert "rebooted" not in result
        assert result.get("error") or result.get("refused")


def session(tmp_path, *, latched=True, last=HOME, status=(), windup=True):
    io = tmp_path / "chunk-io-b"
    io.mkdir()
    rows = [{"command": "run park", "ok": True, "state": last, "t": 101.0}] + list(status)
    (io / "chunk-status.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    library = tmp_path / "lib.json"
    library.write_text(json.dumps({"chunks": {"home": [HOME]}}))
    log = tmp_path / "motor-health-1.jsonl"
    samples = []
    for k in range(8):
        pwm = 30 if k < 3 or not windup else 261 + 17 * (k - 3)
        samples.append({"event": "sample", "sample_time": 200.0 + k, "motors": [
            {"joint": j, "usb_port": "/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_7F31FF061D2D-if00",
             "command_raw": 3134 if j == "elbow_flex" else 2048,
             "present_raw": 3123 if j == "elbow_flex" and k >= 3 and windup else (3134 if j == "elbow_flex" else 2048),
             "pwm": pwm if j == "elbow_flex" else 0, "pwm_limit": 600} for j in oi.push_replay.jp.MOTORS]})
    log.write_text("\n".join(json.dumps(s) for s in samples))
    faults = tmp_path / "faults"
    faults.mkdir()
    (faults / "arm_b_follower-20261103T042721-a3644c.json").write_text(json.dumps({"session_id": SID}))
    for view in ("top", "side"):
        (faults / f"arm_b_follower-20261103T042721-a3644c-{view}.jpg").write_bytes(b"\xff\xd8" + view.encode() * 20)
    record = {"safe_end": not latched, "started": 100.0, "torque_after": {str(i): 0 for i in range(11, 17)},
              "hardware_faults": {"13": {"hw_error": 32, "packet_alert": True}} if latched else {},
              "chunks": {"io": str(io), "library": str(library)}, "motor_health_log": str(log),
              "motor_health_state": str(tmp_path / "motor-health-current.json"), "motor_health_owner": "arm_b_follower",
              "motor_health_session": SID}
    path = tmp_path / "session.json"
    path.write_text(json.dumps(record))
    return path


class Link:
    """What the control PC sees of Fleet: post a report, ask the hold. `down` is an unreachable Fleet."""
    source_id = "omx_arm_b"

    def __init__(self):
        self.posted, self.down, self.held = [], False, False

    def post(self, report):
        if self.down:
            raise OSError("Fleet unreachable")
        self.posted.append(report)
        self.held = True
        return Accepted(incident_id="a" * 32, hold=hold(True))

    def hold(self):
        if self.down:
            raise OSError("Fleet unreachable")
        return hold(self.held)


def hold(held):
    return Hold(held=held, incident_ids=["a" * 32] if held else [], reason="1 open arm incident(s): overload" if held else None)


def test_the_13_27_overload_is_rebooted_reported_to_fleet_and_held_for_a_person(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rebooted, link = [], Link()
    out = oi.handle(session(tmp_path), "arm_b", act=lambda ids: rebooted.append(ids) or {"rebooted": ids}, link=link)
    assert rebooted == [[13]] and out["decision"]["hold"] and out["facts"]["folded"] and out["reported"]
    assert "overload" in out["decision"]["reason"] and "wind-up" in out["decision"]["reason"]
    [report] = link.posted
    assert report.source_id == "omx_arm_b" and report.session_id == SID and report.recovery == {"rebooted": [13]}
    assert [f.role for f in report.frames] == ["top", "side"]
    assert report.facts["latched"]["13"]["bits"] == ["overload"] and report.facts["folded"] is True
    assert "frames" not in report.facts and all("/" not in name for name in report.facts["fault_records"])
    assert not oi.outbox("arm_b")
    assert not list(Path(out["folder"]).glob("agenda.md"))  # Fleet is the ledger; the local copy is incident.json
    row = json.loads((tmp_path / "decisions.jsonl").read_text().splitlines()[-1])
    assert row["stage"] == "incident" and row["chosen"] == ["reboot_latched", "hold_for_person"]
    with pytest.raises(SystemExit, match="held for a person"):
        oi.refuse_if_held("arm_b", link)  # Fleet says held
    link.held = False  # a named operator cleared it in the Fleet console
    oi.refuse_if_held("arm_b", link)
    assert oi.held("arm_b") is None


def test_fleet_unreachable_keeps_the_report_and_the_hold_until_fleet_answers_not_held(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    link = Link()
    link.down = True
    out = oi.handle(session(tmp_path), "arm_b", link=link)
    assert out["incident"] and not out["reported"] and len(oi.outbox("arm_b")) == 1 and oi.held("arm_b")
    with pytest.raises(SystemExit, match="Fleet not reached"):
        oi.refuse_if_held("arm_b", link)  # unreachable: the local hold refuses
    link.down = False
    with pytest.raises(SystemExit, match="held for a person"):
        oi.refuse_if_held("arm_b", link)  # the unsent report went first, so Fleet now holds the arm
    assert not oi.outbox("arm_b") and [r.session_id for r in link.posted] == [SID]
    link.held = False
    oi.refuse_if_held("arm_b", link)
    assert oi.held("arm_b") is None


def test_an_unreachable_fleet_does_not_refuse_an_arm_without_a_local_hold_and_no_link_is_the_same(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    link = Link()
    link.down = True
    oi.refuse_if_held("arm_b", link)
    monkeypatch.setattr(oi, "link_for", lambda arm: None)
    oi.refuse_if_held("arm_b")
    oi.refuse_if_held(None)


def test_fleet_not_held_does_not_lift_a_hold_while_a_report_is_still_unsent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    link = Link()
    link.down = True
    oi.handle(session(tmp_path), "arm_b", link=link)

    class Flaky(Link):  # Fleet answers the hold but refuses the report
        def post(self, report):
            raise OSError("422")

        def hold(self):
            return hold(False)

    with pytest.raises(SystemExit, match="held for a person"):
        oi.refuse_if_held("arm_b", Flaky())
    assert oi.held("arm_b") and len(oi.outbox("arm_b")) == 1


def test_the_same_session_reported_twice_is_the_same_session_id(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    link = Link()
    path = session(tmp_path)
    oi.handle(path, "arm_b", link=link)
    oi.handle(path, "arm_b", link=link)
    assert {r.session_id for r in link.posted} == {SID}


def test_a_contact_stop_reports_what_the_trace_read_and_the_frames_of_the_stop(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    trace = tmp_path / "trace.jsonl"
    rows = [{"t": 100 + i / 30, "chunk": "lift_pick", "sent": [0, 0, 0, 32.6 + 3 * i / 30, 0, 48.8], "present": [0, 0, 0, 32.1 + 0.1 * i / 30, 0, 53.8]} for i in range(44)]
    trace.write_text("\n".join(json.dumps(r) for r in rows))
    monkeypatch.setenv("ROSY_CHUNK_TRACE", str(trace))
    status = [{"error": "contact in lift_pick: wrist_flex lag rose to 2.2 units"}, {"error": "contact in park: the jaws stopped 5.0 units short"}]
    reading = oi.stop_reading(status)
    assert reading["chunk"] == "lift_pick" and reading["verdict"] == "blocked" and reading["joint"] == "wrist_flex"
    assert oi.stop_reading(status[1:]) is None  # only a refused fold: nothing moved to read
    trace.write_text("not json")
    assert oi.stop_reading(status)["verdict"] == "undetermined"  # a damaged trace must not lose the report
    oi.STILLS.mkdir(parents=True)
    for name in ("arm_b-wrist", "arm_b-top", "arm_b-side", "arm_a-top"):
        (oi.STILLS / f"{name}.jpg").write_bytes(b"\xff\xd8x")
    assert sorted(Path(p).stem for p in oi.stills_of("arm_b", 0)) == ["arm_b-side", "arm_b-top"]  # the two the prompt names
    assert oi.stills_of("arm_b", 9e12) == [] and oi.stills_of(None, 0) == []  # another session's are not this one's


def test_the_local_clear_command_is_gone(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        oi.main(["clear", "--arm", "arm_b", "--by", "operator", "--note", "x"])

def test_an_extended_arm_s_load_latch_is_rebooted_where_it_rests_and_stays_held(tmp_path, monkeypatch):
    """D-1079 (was: never rebooted unfolded). reboot_latched reads all six torques 0 on the bus before it acts, so the arm already
    rests where it is and the reboot changes nothing that holds it; the hold stays until the fold brings it home."""
    monkeypatch.chdir(tmp_path)
    acted = []
    out = oi.handle(session(tmp_path, last=[0.8, -20.0, 10.0, 51.4, 45.0, 54.4]), "arm_b",
                    act=lambda ids: acted.append(ids) or {"rebooted": ids})
    assert out["decision"]["hold"] and out["decision"]["actions"] == ["reboot_latched"] and acted and out["recovery"] == {"rebooted": acted[0]}


def test_a_clean_session_is_no_incident_and_a_reopened_catch_is_a_note_without_hold(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert oi.handle(session(tmp_path, latched=False, windup=False), "arm_b") == {"incident": False}
    caught = {"command": "grip", "ok": False, "caught": True, "error": "the jaws stopped; reopened", "t": 150.0}
    (tmp_path / "x").mkdir()
    link = Link()
    out = oi.handle(session(tmp_path / "x", latched=False, windup=False, status=[caught]), "arm_b", link=link)
    assert out["incident"] and not out["decision"]["hold"] and oi.held("arm_b") is None and not link.posted


def test_a_session_that_never_reached_the_arm_is_no_incident(tmp_path, monkeypatch):
    """2026-11-03 23:19: a missing leader port failed the session before the bus opened; it wrote only health keys."""
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "session.json"
    path.write_text(json.dumps({"motor_health_log": "x", "motor_health_snapshot_error": "y"}))
    assert oi.handle(path, "arm_b") == {"incident": False} and not (tmp_path / "incidents").exists()


def test_a_guard_stop_that_ended_the_session_is_an_incident(tmp_path, monkeypatch):
    """2026-11-03 23:48: the wrist roll stopped at +29 against its cable and the guard ended the session."""
    monkeypatch.chdir(tmp_path)
    stop = {"command": "tick", "ok": False, "t": 150.0,
            "fault": "session ended: ValueError: wrist_roll: following error >5 motor degrees"}
    out = oi.handle(session(tmp_path, latched=False, windup=False, status=[stop]), "arm_b")
    assert out["incident"] and out["decision"]["hold"] and "wrist_roll" in out["decision"]["reason"]


def test_an_unsent_report_follows_the_arm_to_another_recording_directory(tmp_path, monkeypatch):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    monkeypatch.chdir(first)
    link = Link()
    link.down = True
    oi.handle(session(first), "arm_b", link=link)
    monkeypatch.chdir(second)
    assert len(oi.outbox("arm_b")) == 1
    link.down = False
    with pytest.raises(SystemExit, match="held for a person"):
        oi.refuse_if_held("arm_b", link)  # Fleet is told of the incident before it can answer "not held"
    assert [r.session_id for r in link.posted] == [SID] and not oi.outbox("arm_b")


def test_a_hold_and_an_outbox_left_in_the_working_directory_by_an_older_version_still_count(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "incidents/outbox").mkdir(parents=True)
    (tmp_path / "incidents/HOLD-arm_b.json").write_text(json.dumps({"reason": "old hold"}))
    old = tmp_path / "incidents/outbox/arm_b-old.json"
    old.write_text("{}")
    assert oi.held("arm_b") == "old hold" and oi.hold_file("arm_b") == Path("incidents/HOLD-arm_b.json")
    assert old.resolve() in [p.resolve() for p in oi.outbox("arm_b")]
    with pytest.raises(SystemExit, match="old hold"):
        oi.refuse_if_held("arm_b")


def test_hold_consumers_read_the_hold_where_the_incident_pipeline_writes_it(tmp_path, monkeypatch):
    import cell_upkeep
    import cell_zones

    here = tmp_path / "elsewhere"
    here.mkdir()
    monkeypatch.chdir(here)
    oi.keep_hold("arm_a", "elbow overload")
    assert cell_upkeep.check_hold("arm_a")["status"] == "fail"
    assert cell_upkeep.check_hold("arm_b")["status"] == "ok"
    z = cell_zones.Zones({"zone_side": "left", "zone_peer": "arm_a", "zone_map_site": "pallet"}, {})
    assert z.incidents is None and z._peer_held()


STOP = {"command": "run descend_pick", "ok": False, "contact": True, "t": 101.5,
        "error": "contact in descend_pick: a joint lagged the command by 1.6 units"}


class Labels(Link):
    """Fleet for a report that does not hold: accepted, the arm stays free; evidence frames are taken one by one."""

    def __init__(self):
        super().__init__()
        self.evidence = []

    def post(self, report):
        if self.down:
            raise OSError("Fleet unreachable")
        self.posted.append(report)
        return Accepted(incident_id="a" * 32, hold=hold(False))

    def post_evidence(self, incident_id, frame):
        self.evidence.append((incident_id, frame.camera, frame.kind, frame.t_rel_s))


def stop_bundle(tmp_path):
    bundle = tmp_path / "incidents" / "evidence" / "20261108T000000000000Z-arm_b-stop"
    bundle.mkdir(parents=True)
    listed = [{"file": "top-tip.jpg"}, {"file": "top--4.0.jpg", "camera": "top", "t_rel_s": -4.0},
              {"file": "top--2.0.jpg", "camera": "top", "t_rel_s": -2.0}, {"file": "side-+1.0.jpg", "camera": "side", "t_rel_s": 1.0}]
    for entry in listed:
        (bundle / entry["file"]).write_bytes(b"\xff\xd8" + entry["file"].encode())
    (bundle / "manifest.json").write_text(json.dumps({"files": listed}))


def test_a_guard_stop_the_recovery_handled_is_reported_for_its_cause_with_its_evidence_and_holds_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stop_bundle(tmp_path)
    link = Labels()
    out = oi.handle(session(tmp_path, latched=False, windup=False, status=[STOP]), "arm_b", link=link)
    assert out["incident"] and out["decision"]["hold"] is False and out["reported"]
    [report] = link.posted
    assert report.decision["hold"] is False and report.facts["stops"][0]["error"].startswith("contact in descend_pick")
    # the jaw tip first, then whole frames from 3 s before the stop on
    assert link.evidence == [("a" * 32, "top", "tip", 0.0), ("a" * 32, "top", "full", -2.0), ("a" * 32, "side", "full", 1.0)]
    assert oi.held("arm_b") is None and not oi.outbox("arm_b") and not oi.label_box("arm_b")
    oi.refuse_if_held("arm_b", link)  # nothing holds the arm


def test_an_unsent_label_report_never_blocks_a_start_and_goes_when_fleet_answers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    link = Labels()
    link.down = True
    out = oi.handle(session(tmp_path, latched=False, windup=False, status=[STOP]), "arm_b", link=link)
    assert not out["reported"] and len(oi.label_box("arm_b")) == 1 and oi.held("arm_b") is None and not oi.outbox("arm_b")
    oi.refuse_if_held("arm_b", link)  # Fleet unreachable and a label unsent: the session still starts
    link.down = False
    oi.refuse_if_held("arm_b", link)
    assert not oi.label_box("arm_b") and len(link.posted) == 1


def test_a_broken_evidence_list_never_stops_a_start(tmp_path, monkeypatch):
    """Review 2026-11-08: a cut sidecar or a pruned bundle raised through refuse_if_held."""
    monkeypatch.chdir(tmp_path)
    link = Labels()
    link.down = True
    oi.handle(session(tmp_path, latched=False, windup=False, status=[STOP]), "arm_b", link=link)
    [report] = oi.label_box("arm_b")
    sidecar = report.with_name(report.stem + ".evidence")
    sidecar.write_text('{"bundle": "gone", "fi')  # cut mid-write
    link.down = False
    oi.refuse_if_held("arm_b", link)
    assert not oi.label_box("arm_b") and not sidecar.exists() and link.evidence == []


def test_a_named_operator_clears_over_the_api_and_the_local_hold_lifts(tmp_path, monkeypatch):
    """2026-11-08: the person checked arm_b; the agent clears with that person's own token, not the arm's."""
    monkeypatch.chdir(tmp_path)
    link = Link()
    oi.handle(session(tmp_path), "arm_b", act=lambda ids: {"rebooted": ids}, link=link)
    assert oi.held("arm_b")
    calls = []

    def clear(incident_id, note, token):
        calls.append((incident_id, note, token))
        link.held = False
        return hold(False)
    link.clear = clear
    token = tmp_path / "operator.token"
    token.write_text("person-token\n")
    token.chmod(0o644)
    with pytest.raises(SystemExit, match="owner only"):
        oi.clear("arm_b", "jaws empty", token, link)
    token.chmod(0o600)
    with pytest.raises(SystemExit, match="note"):
        oi.clear("arm_b", "  ", token, link)
    assert oi.clear("arm_b", "jaws empty", token, link) == 0
    assert calls == [("a" * 32, "jaws empty", "person-token")]
    assert oi.held("arm_b") is None


ALIGN = ("session ended: ValueError: follower: alignment deadline exceeded; current={'shoulder_pan': 2105, 'gripper': 2034}, "
         "target={'shoulder_pan': 2063, 'gripper': 2034}, command={'shoulder_pan': 2105.79, 'gripper': 2034.0}; last sample age=0.03")


def test_a_software_stop_on_a_folded_arm_that_followed_its_command_is_listed_and_holds_nothing(tmp_path, monkeypatch):
    """2026-11-09 02:21: a jog sent before the guard tracked crawled into its alignment deadline on both arms."""
    monkeypatch.chdir(tmp_path)
    link = Labels()
    stop = {"command": "tick", "ok": False, "t": 150.0, "fault": ALIGN}
    out = oi.handle(session(tmp_path, latched=False, windup=False, status=[stop]), "arm_b", link=link)
    assert out["decision"]["hold"] is False and "alignment deadline" in out["decision"]["reason"] and out["reported"]
    assert oi.held("arm_b") is None and link.posted[0].decision["hold"] is False
    # the arm lagging its command (something pushed back) or an arm not folded still holds
    for i, (other, last) in enumerate(((ALIGN.replace("2105.79", "2200.0"), HOME), (ALIGN, [20.0] + HOME[1:]))):
        case = tmp_path / f"case{i}"
        case.mkdir()
        monkeypatch.chdir(case)
        lagging = {"command": "tick", "ok": False, "t": 150.0, "fault": other}
        assert oi.handle(session(case, latched=False, windup=False, last=last, status=[lagging]), "arm_b")["decision"]["hold"]


def test_status_and_clear_with_cause_basis_and_env_discovery(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    env_file = tmp_path / "bridge.env"
    env_file.write_text('ROSY_WORKCELL_OBSERVATIONS="/tmp/obs.yaml"\n# comment\nROSY_OBSERVATION_WORKCELL="cell_a"\n')
    monkeypatch.setenv("ROSY_OBSERVATION_BRIDGE_ENV", str(env_file))
    parsed = oi._bridge_environ()
    assert parsed["ROSY_WORKCELL_OBSERVATIONS"] == "/tmp/obs.yaml" and parsed["ROSY_OBSERVATION_WORKCELL"] == "cell_a"

    link = Link()
    oi.handle(session(tmp_path), "arm_b", act=lambda ids: {"rebooted": ids}, link=link)
    st = oi.status("arm_b", link)
    assert st["local_held"] is True and st["fleet_held"] is True and st["incident_ids"] == ["a" * 32]

    calls = []
    def clear(incident_id, note, token, *, cause=None, basis=None):
        calls.append((incident_id, note, token, cause, basis))
        link.held = False
        return hold(False)
    link.clear = clear
    token = tmp_path / "cell-a-operator-test.token"
    token.write_text("op-token\n")
    token.chmod(0o600)
    monkeypatch.setenv("ROSY_OPERATOR_TOKEN_FILE", str(token))
    assert oi.clear("arm_b", "checked home", None, link, cause="software_or_config", basis="measured") == 0
    assert calls == [("a" * 32, "checked home", "op-token", "software_or_config", "measured")]
    assert oi.status("arm_b", link)["fleet_held"] is False

    # Pre-2026-11-08/09 Fleet servers return held=True for a single non-holding label or folded software-stop report
    for non_hold_reason in (
        "1 open arm incident(s): " + "b" * 32 + "; reported for a person's cause, the arm is not held",
        "1 open arm incident(s): software stop (alignment deadline exceeded) with the arm folded on its command; nothing physical held it",
    ):
        label_only = Hold(held=True, incident_ids=["b" * 32], reason=non_hold_reason)
        assert oi._effectively_held(label_only) is False
        link.hold = lambda answer=label_only: answer
        oi.refuse_if_held("arm_b", link)
        assert oi.held("arm_b") is None

    # Older Fleet servers reject cause/basis with HTTP 422; clear() retries without cause/basis
    fallback_calls = []
    def clear_422(incident_id, note, token, *, cause=None, basis=None):
        fallback_calls.append((incident_id, note, token, cause, basis))
        if cause is not None or basis is not None:
            err = OSError("HTTP Error 422: Unprocessable Entity")
            err.code = 422
            raise err
        link.held = False
        return hold(False)
    link.held = True
    link.hold = lambda: hold(link.held)
    link.clear = clear_422
    assert oi.clear("arm_b", "checked home", None, link, cause="software_or_config", basis="seen") == 0
    assert fallback_calls == [
        ("a" * 32, "checked home", "op-token", "software_or_config", "seen"),
        ("a" * 32, "checked home", "op-token", None, None),
    ]


def test_decide_handles_torque_after_open_error_string_without_crashing(tmp_path, monkeypatch):
    """2026-11-10 20:06: USB disconnect during session teardown wrote {'open': 'error: ...'} to torque_after."""
    monkeypatch.chdir(tmp_path)
    s = session(tmp_path, latched=False, windup=False)
    data = json.loads(s.read_text())
    data["safe_end"] = False
    data["torque_after"] = {"open": "error: a physically confirmed /dev/serial/by-id symlink is required"}
    data["caps_restored"] = ["follower 11: a physically confirmed /dev/serial/by-id symlink is required"]
    s.write_text(json.dumps(data))
    out = oi.handle(s, "arm_b", link=Link())
    assert out["decision"]["hold"] is True
    assert "torque not confirmed OFF" in out["decision"]["reason"]
    assert "caps not confirmed restored" in out["decision"]["reason"]


def test_handle_filters_leader_keys_from_latched_reboot(tmp_path, monkeypatch):
    """2026-11-16 00:03: leader hw_error recorded 'leader 6' in latched; act() only receives follower ints."""
    monkeypatch.chdir(tmp_path)
    s = session(tmp_path, latched=False, windup=False)
    data = json.loads(s.read_text())
    data["hardware_faults"] = {"leader 6": {"hw_error": 32}, "13": {"hw_error": 32}}
    s.write_text(json.dumps(data))
    called = []
    out = oi.handle(s, "arm_b", act=lambda ids: called.append(ids) or {"rebooted": ids}, link=Link())
    assert called == [[13]]
    assert set(out["facts"]["latched"]) == {"leader 6", "13"}


def test_sync_hold_from_fleet_and_clear_with_explicit_core_token_and_healthy_caps(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    oi.keep_hold("arm_b", "caps not confirmed restored")
    assert oi.held("arm_b")

    class SyncLink(Link):
        def __init__(self):
            self.held_flag = True
            self.cleared = []

        def hold(self):
            return hold(self.held_flag)

        def clear(self, incident_id, note, token, cause=None, basis=None):
            self.cleared.append((incident_id, note, token))
            self.held_flag = False
            return hold(False)

    link = SyncLink()
    assert oi.sync_hold_from_fleet("arm_b", link=link) is False
    assert oi.clear("arm_b", "verified home", link=link, token="jwt.core.token") == 0
    assert link.cleared == [("a" * 32, "verified home", "jwt.core.token")]
    assert oi.held("arm_b") is None

    oi.keep_hold("arm_b", "stale")
    assert oi.sync_hold_from_fleet("arm_b", link=link) is True
    assert oi.held("arm_b") is None

    # Healthy caps_restored=True must not falsely report "caps not confirmed restored".
    d = oi.decide({"safe_end": False, "latched": {}, "windup_hits": [], "flagged": [],
                   "torque_after": {"11": 0}, "caps_restored": True, "folded": True, "stops": []})
    assert "caps not confirmed restored" not in d["reason"]
    assert "unsafe session end" in d["reason"]


def test_telemetry_sync_clears_local_hold_via_machine_sync_without_operator_token(tmp_path, monkeypatch):
    import cell_camera_telemetry_sync as sync_mod

    monkeypatch.chdir(tmp_path)
    oi.keep_hold("arm_b", "caps not confirmed restored")
    monkeypatch.setattr(oi, "link_for", lambda arm: type("L", (), {
        "hold": staticmethod(lambda: hold(False)),
    })())

    class FakeResp:
        def __init__(self, payload):
            self.payload = payload

        def read(self):
            return json.dumps(self.payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(req, context=None, timeout=None):
        if req.full_url.endswith("/state.json"):
            return FakeResp({})
        return FakeResp({"ok": True, "pending_clear_arms": {"arm_b": "cleared via Fleet core"}})

    out = sync_mod.sync_cell_telemetry("https://fleet.example:8443", "svc-tok", prep_dir=tmp_path, urlopen_fn=fake_urlopen)
    assert out["ok"] is True
    assert oi.held("arm_b") is None


def test_verified_baseline_caps_releases_clean_folded_arm_without_human_hold(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s = session(tmp_path, latched=False, windup=False)
    data = json.loads(s.read_text())
    data["safe_end"] = False
    data["caps_restored"] = ["follower 12 pwm_limit: baseline caps require confirmed follower model/mode and torque OFF"]
    s.write_text(json.dumps(data))

    held_out = oi.handle(s, "arm_b", link=Link(), verify_caps=lambda: False)
    assert held_out["decision"]["hold"] is True and oi.held("arm_b") is not None
    oi.hold_file("arm_b").unlink()

    class NonHoldLink(Link):
        def post(self, report):
            from core_common.protocol.arm_incident.arm_incidents import ArmIncidentAccepted
            return ArmIncidentAccepted(incident_id="a" * 32, hold=hold(bool(report.decision.get("hold"))))

    free_out = oi.handle(s, "arm_b", link=NonHoldLink(), verify_caps=lambda: True)
    assert free_out["decision"]["hold"] is False and free_out["facts"]["caps_verified_restored"] is True
    assert oi.held("arm_b") is None


def test_report_for_filters_non_contract_wrist_still_and_duplicate_roles(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    oi.STILLS.mkdir(parents=True)
    top = oi.STILLS / "arm_s-top.jpg"
    wrist = oi.STILLS / "arm_s-wrist.jpg"
    top_dup = tmp_path / "extra-top.jpg"
    top.write_bytes(b"\xff\xd8" + b"top" * 10)
    wrist.write_bytes(b"\xff\xd8" + b"wrist" * 10)
    top_dup.write_bytes(b"\xff\xd8" + b"dup" * 10)

    s = session(tmp_path, latched=False, windup=False, status=[
        {"command": "human-hold", "fault": "human hold", "person_needed": True, "t": 150.0},
    ])
    for p in (tmp_path / "faults").glob("*"):
        p.unlink()

    link = Link()
    out = oi.handle(s, "arm_s", link=link)
    assert out["reported"] is True
    assert len(link.posted) == 1
    assert [f.role for f in link.posted[0].frames] == ["top"]
    assert sorted(Path(p).name for p in out["facts"]["frames"]) == ["arm_s-top.jpg", "arm_s-wrist.jpg"]

    report = oi.report_for(
        "omx_arm_s",
        SID,
        {"safe_end": True, "latched": {}, "windup_hits": [], "fault_records": [],
         "frames": [str(wrist), str(top), str(top_dup)]},
        {"hold": True, "actions": [], "offered": [], "reason": "human hold"},
        None,
    )
    assert len(report.frames) == 1 and report.frames[0].role == "top"


def test_rows_reads_tail_chunks_backward_stopping_before_since(tmp_path, monkeypatch):
    import omx_incident_reading as reading

    p = tmp_path / "chunk-status.jsonl"
    pad = "x" * 1000
    old_rows = [json.dumps({"t": 10.0, "pad": pad}) for _ in range(90)]
    old_rows.insert(10, "{corrupt-early")
    stop_row = json.dumps({"t": 50.0, "msg": "before-since"})
    boundary_row = json.dumps({"t": 100.0, "pad": pad})
    tail = "\n".join(old_rows + [stop_row, boundary_row, "{corrupt-tail", json.dumps({"t": 101.0}), json.dumps({"t": 105.0})]) + "\n"
    p.write_text(tail, encoding="utf-8")

    bytes_read = [0]
    orig_open = Path.open

    def tracked_open(self, mode="r", *args, **kwargs):
        f = orig_open(self, mode, *args, **kwargs)
        if self == p and "b" in mode:
            orig_read = f.read
            def counting_read(n=-1):
                data = orig_read(n)
                bytes_read[0] += len(data)
                return data
            f.read = counting_read
        return f

    monkeypatch.setattr(Path, "open", tracked_open)
    got = reading.rows(p, since=100.0)
    assert [r["t"] for r in got] == [100.0, 101.0, 105.0]
    assert 0 < bytes_read[0] < p.stat().st_size

    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    assert reading.rows(empty, since=10.0) == []
    assert reading.rows(tmp_path / "missing.jsonl", since=10.0) == []


REST = [0.22, -58.53, 54.68, 49.84, -4.66, 53.6]  # 2026-11-27 arm_s: torque OFF relaxed the elbow from 50.4 to 54.7 on its rest pose
S_HOME = [0.22, -58.9, 50.4, 49.8, -4.7, 53.6]


def _torque_off_session(tmp_path, last, library):
    s = session(tmp_path, latched=False, windup=False, last=last)
    (tmp_path / "lib.json").write_text(json.dumps(library))
    return s


def test_a_rested_folded_arm_opens_no_extended_incident_and_folded_is_not_widened(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s = _torque_off_session(tmp_path, REST, {"chunks": {"home": [S_HOME]}})
    assert oi.handle(s, "arm_s") == {"incident": False}
    f = oi.facts(json.loads(s.read_text()), S_HOME, "arm_s", {"chunks": {"home": [S_HOME]}})
    assert f["folded"] is False and f["rested_folded"] is True  # D-1047: only the HOME_TOL rule is "folded"


@pytest.mark.parametrize("last", [REST, [19.0] + REST[1:]], ids=["rested", "off-rest"])
def test_a_latched_arm_keeps_its_latch_hold_not_the_extended_one(tmp_path, monkeypatch, last):
    """Removing the 'not latched' guard of decide()'s guarded branch would give the off-rest arm the "arm extended"
    reason (a rested one skips that branch on its own), so the off-rest case is what pins the guard."""
    monkeypatch.chdir(tmp_path)
    out = oi.handle(session(tmp_path, latched=True, windup=False, last=last), "arm_s", home=S_HOME, link=Link())
    assert out["decision"]["hold"] and "arm extended" not in out["decision"]["reason"]
    assert out["decision"]["reason"].startswith("latched ID 13")


def test_the_loose_fold_ranges_alone_do_not_rest_an_arm_far_from_its_home(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    lib = {"chunks": {"home": [S_HOME]}}
    far = [19.0] + REST[1:]  # inside FOLD_TOL pan 20, outside REST_TOL
    s = _torque_off_session(tmp_path, far, lib)
    f = oi.facts(json.loads(s.read_text()), S_HOME, "arm_s", lib)
    assert f["folded"] is False and f["rested_folded"] is False


def test_nine_units_off_home_still_opens_the_extended_incident_and_seven_does_not(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    lib = {"chunks": {"home": [S_HOME]}}
    nine = list(S_HOME); nine[2] += 9.0
    nine_dir = tmp_path / "nine"
    nine_dir.mkdir()
    out = oi.handle(_torque_off_session(nine_dir, nine, lib), "arm_s", link=Link())
    assert out["decision"]["hold"] and "arm extended" in out["decision"]["reason"]
    seven = list(S_HOME); seven[2] += 7.0
    assert oi.handle(_torque_off_session(tmp_path, seven, lib), "arm_s") == {"incident": False}


def test_a_really_extended_arm_with_torque_off_still_opens_the_guarded_fold_incident(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s = _torque_off_session(tmp_path, [0.22, -20.0, 20.0, 49.8, -4.7, 53.6], {"chunks": {"home": [S_HOME]}})
    out = oi.handle(s, "arm_s", link=Link())
    assert out["decision"]["hold"] and "arm extended" in out["decision"]["reason"]


def test_without_a_library_pose_the_coarse_rule_never_rests_the_incident_fact(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s = _torque_off_session(tmp_path, REST, {"chunks": {}})
    out = oi.handle(s, "arm_s", home=S_HOME, link=Link())
    assert out["decision"]["hold"] and "arm extended" in out["decision"]["reason"]


def test_a_missing_or_malformed_library_is_tolerated_when_home_is_passed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s = _torque_off_session(tmp_path, REST, {"chunks": {}})
    rec = json.loads(s.read_text())
    for body in (None, "{not json"):
        lib = tmp_path / "lib.json"
        lib.unlink(missing_ok=True)
        if body:
            lib.write_text(body)
        out = oi.handle(s, "arm_s", home=S_HOME, link=Link())
        assert out["decision"]["hold"] and "arm extended" in out["decision"]["reason"]


def _run(tmp_path, name, last, library=None, **kw):
    """One handle() over its own session folder; `safe_end` False rewrites the record."""
    d = tmp_path / name
    d.mkdir()
    s = session(d, latched=False, windup=kw.pop("windup", False), last=last, status=kw.pop("status", ()))
    if library is not None:
        (d / "lib.json").write_text(json.dumps(library))
    if kw.pop("unsafe", False):
        rec = json.loads(s.read_text())
        rec["safe_end"] = False
        s.write_text(json.dumps(rec))
    return oi.handle(s, "arm_s", home=kw.pop("home", S_HOME), link=Link(), **kw)


def _link_loss_facts():
    """A torque-off pose 4.3 units off home (inside REST_TOL, outside HOME_TOL) with the USB-loss rows is_home_recovery needs."""
    return {"safe_end": True, "caps_restored": True, "folded": False, "latched": {}, "windup_hits": [], "stops": [],
            "stop_reading": None, "torque_after": {str(i): 0 for i in range(11, 17)}, "home": S_HOME, "last_state": REST,
            "last_target": None, "last_command": None, "rested_folded": True, "flagged_total": 1,
            "flagged": [{"error": "session ended: RuntimeError: torque OFF not confirmed: DeviceNotConnectedError", "caught": False}],
            "fault_records": ["f.json"], "fault_records_total": 1,
            "fault_record_kinds": [{"fault": "(5, 'Input/output error')", "stop_reasons": []}]}


def test_a_rested_link_loss_keeps_the_guarded_home_recovery_decision_of_main():
    from core_common.protocol.arm_incident.home_recovery import HOME_RECOVERY_REASON, guarded_home_decision, is_home_recovery
    f = _link_loss_facts()
    assert is_home_recovery(f)
    d = oi.decide(f)  # what origin/main returns: the rested fact is not read for this case
    assert d == guarded_home_decision(f) == {"actions": [], "hold": True, "offered": [], "reason": HOME_RECOVERY_REASON,
                                            "event_kind": "home_recovery"}
    other = dict(f, flagged=[{"error": "pushing joint", "caught": False}])  # same pose, not a link loss: rested wins
    assert not is_home_recovery(other)
    assert oi.decide(other)["hold"] and "arm extended" not in oi.decide(other)["reason"]


def test_a_rested_pose_with_a_physical_sign_is_still_held_and_a_guard_stop_is_label_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    lib = {"chunks": {"home": [S_HOME]}}
    wound = _run(tmp_path, "windup", REST, lib, windup=True)
    assert wound["decision"]["hold"] and "wind-up" in wound["decision"]["reason"]
    unsafe = _run(tmp_path, "unsafe", REST, lib, unsafe=True)
    assert unsafe["decision"]["hold"] and "arm extended" not in unsafe["decision"]["reason"]
    stop = {"command": "run lift", "error": "contact in lift: strain", "state": REST, "t": 102.0}
    label = _run(tmp_path, "stop", REST, lib, status=[stop])
    assert label["decision"]["hold"] is False and "arm extended" not in label["decision"]["reason"]
    assert label["facts"]["stops"] and label["facts"]["rested_folded"] is True


def test_a_bad_library_still_raises_for_the_home_lookup_but_only_unrests_when_home_is_passed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for n, (body, error) in enumerate([(None, OSError), ("{not json", ValueError), ("[1]", AttributeError),
                                       ('"x"', AttributeError)]):  # what origin/main raises for each
        d = tmp_path / f"bad{n}"
        d.mkdir()
        s = session(d, latched=False, windup=False, last=REST)
        lib = d / "lib.json"
        lib.unlink()
        if body:
            lib.write_text(body)
        with pytest.raises(error):
            oi.handle(s, "arm_s", link=Link())
        out = oi.handle(s, "arm_s", home=S_HOME, link=Link())
        assert out["facts"]["rested_folded"] is False and "arm extended" in out["decision"]["reason"]


def test_rest_tolerance_is_inclusive_at_eight_units(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    home = [0.0, -58.0, 50.0, 50.0, -5.0, 53.6]  # whole numbers: 8.0 off is exactly 8.0 in floats
    lib = {"chunks": {"home": [home]}}
    on = list(home); on[2] += 8.0
    assert _run(tmp_path, "on", on, lib, home=home) == {"incident": False}
    off = list(home); off[2] += 8.1
    out = _run(tmp_path, "off", off, lib, home=home)
    assert out["decision"]["hold"] and "arm extended" in out["decision"]["reason"]


def test_a_multi_frame_home_chunk_uses_its_first_frame_for_the_lookup_and_the_rested_fact(tmp_path, monkeypatch):
    """handle() takes home = chunks.home[0]; rested_folded is measured against that same frame (facts["home"])."""
    monkeypatch.chdir(tmp_path)
    second = list(S_HOME); second[2] += 20.0
    lib = {"chunks": {"home": [S_HOME, second]}}
    out = _run(tmp_path, "first", REST, lib, home=None)  # rests on frame 0 only
    assert out == {"incident": False}
    near_second = list(second); near_second[2] += 4.3
    out = _run(tmp_path, "second", near_second, lib, home=None)  # rests on frame 1 only
    assert out["facts"]["home"] == S_HOME and out["facts"]["rested_folded"] is False
    assert out["decision"]["hold"] and "arm extended" in out["decision"]["reason"]
