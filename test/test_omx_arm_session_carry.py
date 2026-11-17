"""D-977 Decision 4: the hardware owner accepts ARM_TRANSFER and runs the folded carry through a (fake) arm session.

Real owner assembly, journal and Action API; the session, its port and the field carry are fakes. No serial, no torque,
no ROS, no signal sent to anything."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for relative in ("contracts/foundation", "middleware/devices/omx/adapter", "middleware/devices/omx/agent/src",
                 "middleware/devices/omx/adapter/test", "operations/fleet", "deploy/robot/omx"):
    if str(ROOT / relative) not in sys.path:
        sys.path.insert(0, str(ROOT / relative))

from core_common.protocol.schemas import FleetArmTransferGrant  # noqa: E402
from fleet.server.ledger.action_receipts import verify_phase_receipt  # noqa: E402
from omx_adapter.action_runner import action_grant_digest  # noqa: E402
from omx_adapter.journal_identity import journal_identity  # noqa: E402
from omx_adapter.transfer_object_bindings import TransferObjectBindings  # noqa: E402
from rosy_agent import presence_token  # noqa: E402
from rosy_agent.arm_session_carry import ArmGoals, Carry, CarryRefused, PHASES  # noqa: E402
from rosy_agent.arm_transfer import ArmTransferInstallation  # noqa: E402
from rosy_agent.omx_hardware_owner import ARM_GOALS_PROFILE, build_hardware_owner  # noqa: E402
from test_omx_hardware_owner import FLEET_UID, FakeRuntime, _config, _settings  # noqa: E402
from test_omx_pose_plan import kin, profile  # noqa: E402,F401
from test_transfer_preflight import _catalog  # noqa: E402
import hardware_owner_goals as goals_module  # noqa: E402

FOLDED = ("goto above_pick", "run descend_pick", "run grasp_pick", "run lift_pick", "park",
          "goto above_place", "run descend_place", "run release_place", "run lift_place", "park")
EPOCH, GENERATION = 2, 8


class FakeSession:
    """The arm session as the owner sees it: a command FIFO with status replies."""

    def __init__(self):
        self.commands, self.folds, self.script, self.gates = [], 0, {}, {}
        self.fold_gate, self.signals = None, []

    def act(self, command):
        self.commands.append(command)
        if command in self.gates:
            self.gates[command][0].set()
            self.gates[command][1].wait(5)
        reply = self.script.get(command, {"ok": True})
        return {"t": 100.0 + len(self.commands), "holding": command in ("run grasp_pick", "run lift_pick"), **reply}

    def fold(self):
        self.folds += 1
        if self.fold_gate is not None:
            self.fold_gate.wait(5)
        return {"ok": True}

    def block(self, command):
        entered, release = threading.Event(), threading.Event()
        self.gates[command] = (entered, release)
        return entered, release


def fake_run(cell):
    """transfer_folded without the camera stack: the same commands, stopping at the first one that does not go through."""
    for command in ("load library.json", *FOLDED):
        status = cell.act(command)
        if not status.get("ok") or status.get("contact"):
            return {"result": "contact" if status.get("contact") else "refused", "at": command}
    return {"result": "placed"}


def build(tmp_path, kin, profile, session, *, timing=None, fence=None, arm_goals=True):
    fence = fence if fence is not None else {"ok": True}
    catalog = _catalog(kin, profile, workcell_id="omx_cell_a", instance_id="omx_cell_a_01",
                       calibration_revision="omx-a-measured-r1")
    installation = ArmTransferInstallation(TransferObjectBindings(catalog, {"object-1": "g1"}), "arm-cap-1", "cfg-1", "d" * 64)
    goals = ArmGoals(installation, lambda grant: Carry(session, fake_run, session.fold, FOLDED),
                     {"poll_s": 0.01, "fence_loss_s": 0.15, "deadline_s": 30, **(timing or {})}) if arm_goals else None
    owner = build_hardware_owner(
        _settings(tmp_path), _config(), runtime_factory=FakeRuntime, refuse_second_owner=lambda: None,
        fleet_fence_current=lambda epoch, generation: fence["ok"], commissioning_revision=lambda: "c7", arm_goals=goals)
    owner.stop.rearm(authority_epoch=EPOCH, dispatch_generation=GENERATION, operator_confirmed=True,
                     fleet_fence_current=lambda epoch, generation: True)
    return owner, installation, fence


def grant(owner, installation):
    catalog, now = installation.bindings.catalog, datetime.now(timezone.utc)
    body = dict(mission_id="m-1", step_id="s-1", action_id="a-1", attempt_id="t-1",
                owner_journal_id=journal_identity(owner.store.path), owner_session_id=owner.runtime.owner.session_id,
                workcell_id=catalog.workcell_id, instance_id=catalog.instance_id, action_kind="ARM_TRANSFER",
                request_digest="0" * 64, capability_revision="arm-cap-1", config_revision="cfg-1",
                authority_epoch=EPOCH, dispatch_generation=GENERATION, issued_at=now, expires_at=now + timedelta(minutes=5),
                arm_transfer=dict(object_ref="object-1", catalog_digest=catalog.digest,
                                  bindings_digest=installation.bindings.revision, source="p1", target="p2",
                                  resource_policy_digest="d" * 64))
    body["request_digest"] = action_grant_digest(body)
    return FleetArmTransferGrant.model_validate(body)


def call(owner, **request):
    return owner.action_api.dispatch({"version": 2, **request}, peer_uid=FLEET_UID)


def submit(owner, g):
    return call(owner, operation="SubmitAction", grant=g.model_dump(mode="json"))


def receipt(owner):
    return call(owner, operation="GetAction", action_id="a-1")["receipt"]


def wait_for(predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError("condition not reached")


def state_is(owner, *states):
    return lambda: receipt(owner)["state"] in states and receipt(owner)


def test_submit_runs_the_four_phases_in_order_and_the_receipt_verifies(tmp_path, kin, profile):
    session = FakeSession()
    owner, installation, _ = build(tmp_path, kin, profile, session)
    g = grant(owner, installation)
    assert submit(owner, g)["status"] == 200
    done = wait_for(state_is(owner, "SUCCEEDED", "HOLD", "FAILED"))
    assert done["state"] == "SUCCEEDED", done
    assert [p["phase_id"] for p in done["phase_summaries"]] == list(PHASES)
    verified = verify_phase_receipt(g, call(owner, operation="GetAction", action_id="a-1"), phase_ids=PHASES)
    assert verified.state.value == "SUCCEEDED"
    assert session.commands == ["load library.json", *FOLDED] and session.folds == 0


def test_a_phase_is_written_before_its_first_command_and_succeeds_only_from_its_own_result(tmp_path, kin, profile):
    session = FakeSession()
    entered, release = session.block("run grasp_pick")  # the grasp phase is under way, approach is done
    owner, installation, _ = build(tmp_path, kin, profile, session)
    submit(owner, grant(owner, installation))
    assert entered.wait(5)
    phases = {p["phase_id"]: p["state"] for p in receipt(owner)["phase_summaries"]}
    assert phases == {"approach": "SUCCEEDED", "grasp": "SUBMITTING"}  # intent first, accepted only after the session answered
    release.set()
    assert wait_for(state_is(owner, "SUCCEEDED"))["state"] == "SUCCEEDED"


def test_a_failed_step_is_a_failed_phase_then_a_fold_and_hold(tmp_path, kin, profile):
    session = FakeSession()
    session.script["run descend_pick"] = {"ok": False, "contact": True, "error": "strain"}
    owner, installation, _ = build(tmp_path, kin, profile, session)
    submit(owner, grant(owner, installation))
    held = wait_for(state_is(owner, "HOLD"))
    assert [(p["phase_id"], p["state"]) for p in held["phase_summaries"]] == [("approach", "FAILED")]
    assert wait_for(lambda: session.folds == 1)
    assert "run grasp_pick" not in session.commands


def test_a_grasp_that_does_not_hold_fails_the_grasp_phase(tmp_path, kin, profile):
    session = FakeSession()
    session.script["run lift_pick"] = {"ok": True, "holding": False}
    owner, installation, _ = build(tmp_path, kin, profile, session)
    submit(owner, grant(owner, installation))
    held = wait_for(state_is(owner, "HOLD"))
    assert [p["state"] for p in held["phase_summaries"]] == ["SUCCEEDED", "FAILED"]
    assert wait_for(lambda: session.folds == 1)


def test_cancel_sends_park_through_the_session_and_signals_nothing(tmp_path, kin, profile):
    session = FakeSession()
    entered, release = session.block("run descend_pick")
    owner, installation, _ = build(tmp_path, kin, profile, session)
    submit(owner, grant(owner, installation))
    assert entered.wait(5)
    cancel = call(owner, operation="CancelAction", action_id="a-1", attempt_id="t-1", reason="operator",
                  requested_at=datetime.now(timezone.utc).isoformat())
    assert cancel["status"] == 200
    assert wait_for(lambda: session.folds == 1)  # the fold goes out while the command is still in flight
    release.set()
    assert wait_for(state_is(owner, "HOLD"))["state"] == "HOLD"
    assert "run grasp_pick" not in session.commands and session.signals == []


def test_the_watchdog_folds_and_holds_after_three_seconds_of_failures_not_before(tmp_path, kin, profile):
    session = FakeSession()
    entered, release = session.block("run descend_pick")
    owner, installation, fence = build(tmp_path, kin, profile, session, timing={"fence_loss_s": 0.3})
    submit(owner, grant(owner, installation))
    assert entered.wait(5)
    fence["ok"] = False
    time.sleep(0.1)
    fence["ok"] = True  # a short glitch must not fold
    time.sleep(0.1)
    assert session.folds == 0
    fence["ok"] = False
    begun = time.monotonic()
    assert wait_for(lambda: session.folds == 1)
    assert time.monotonic() - begun >= 0.25
    release.set()
    assert wait_for(state_is(owner, "HOLD"))


def test_the_deadline_never_interrupts_a_fold_in_progress(tmp_path, kin, profile):
    session = FakeSession()
    session.fold_gate = threading.Event()
    entered, release = session.block("run descend_pick")
    owner, installation, fence = build(tmp_path, kin, profile, session, timing={"deadline_s": 0.05})
    submit(owner, grant(owner, installation))
    assert entered.wait(5)
    assert wait_for(lambda: session.folds == 1)  # the deadline began the fold
    fence["ok"] = False
    time.sleep(0.4)  # many deadlines and a lost fence later: still the one fold, still running
    assert session.folds == 1 and receipt(owner)["state"] not in ("HOLD", "SUCCEEDED")
    release.set()
    session.fold_gate.set()
    assert wait_for(state_is(owner, "HOLD"))
    assert session.folds == 1


def test_goals_are_off_without_a_local_arm_goals_config(tmp_path, kin, profile):
    owner, installation, _ = build(tmp_path, kin, profile, FakeSession(), arm_goals=False)
    identity = call(owner, operation="GetOwnerIdentity")["identity"]
    assert identity["goals_enabled"] is False and identity["simulation"] is False
    refused = submit(owner, grant(owner, installation))
    assert refused["status"] != 200 and call(owner, operation="GetAction", action_id="a-1").get("receipt") is None


def test_goals_on_report_a_device_identity_with_the_commissioning_revision(tmp_path, kin, profile):
    owner, _, _ = build(tmp_path, kin, profile, FakeSession())
    identity = call(owner, operation="GetOwnerIdentity")["identity"]
    assert (identity["goals_enabled"], identity["device"], identity["simulation"], identity["commissioning_revision"],
            identity["profile"]) == (True, True, False, "c7", ARM_GOALS_PROFILE)


def test_goals_need_a_commissioning_record(tmp_path, kin, profile):
    installation = build(tmp_path / "a", kin, profile, FakeSession())[1]
    with pytest.raises(ValueError, match="commissioning"):
        build_hardware_owner(_settings(tmp_path / "b"), _config(), runtime_factory=FakeRuntime,
                             refuse_second_owner=lambda: None, fleet_fence_current=lambda e, g: True,
                             arm_goals=ArmGoals(installation, lambda grant: None))


SECTION = {"device_trial_arms": ["omx_cell_a_01"], "installation": "/i.json", "installation_spec": "/s.yaml",
           "cell_config": "/c.json", "libraries": {"source>target": "/lib.json"}, "presence_token": "/run/t"}


def test_the_goals_section_names_exactly_this_one_arm_and_needs_commissioning():
    parse = lambda section, root="/c": goals_module.parse(section, instance_id="omx_cell_a_01", commissioning_root=root)  # noqa: E731
    assert parse(None) is None and parse(SECTION) == SECTION
    for bad in ({**SECTION, "device_trial_arms": ["omx_cell_a_01", "omx_cell_b_01"]},
                {**SECTION, "device_trial_arms": ["other"]}, {**SECTION, "libraries": {}},
                {**SECTION, "cell_config": "relative.json"}, {k: v for k, v in SECTION.items() if k != "cell_config"}):
        with pytest.raises(ValueError):
            parse(bad)
    with pytest.raises(ValueError, match="commissioning_root"):
        parse(SECTION, None)


def _token(path, age_s=0.0, mode=0o600):
    path.write_text("")
    path.chmod(mode)
    os.utime(path, (time.time() - age_s,) * 2)
    return path


def test_the_presence_token_is_single_use_short_lived_and_private(tmp_path):
    assert presence_token.consume(tmp_path / "none") is False
    fresh = _token(tmp_path / "fresh")
    assert presence_token.consume(fresh) is True and not fresh.exists() and presence_token.consume(fresh) is False
    stale = _token(tmp_path / "stale", age_s=presence_token.MAX_AGE_S + 5)
    assert presence_token.consume(stale) is False and not stale.exists()  # taken away, never honoured
    shared = _token(tmp_path / "shared", mode=0o666)
    assert presence_token.consume(shared) is False and shared.exists()


def test_commissioning_is_passed_to_a_carry_only_for_a_fresh_token_and_never_from_the_grant(tmp_path):
    seen = []

    def open_cell(args, commissioning):
        seen.append(commissioning)
        return {}, "fifo", "cal.json", tmp_path

    gate = SimpleNamespace(open=lambda library, before: None, act=lambda c: {"ok": True})
    field = SimpleNamespace(
        open_cell=open_cell, Guarded=lambda cell, config: cell, Gate=lambda *a, **k: gate, FOLDED=FOLDED,
        transfer_folded=lambda *a, **k: {"result": "placed"}, fold=lambda fifo: {"ok": True},
        attempts=SimpleNamespace(begin=lambda *a: None), calibration=SimpleNamespace(load=lambda p: {}),
        pivot=SimpleNamespace(with_site_maps=lambda config, cal: cal))
    token = tmp_path / "presence"
    open_carry = goals_module.open_carry_for({**SECTION, "presence_token": str(token)}, field=field)
    g = SimpleNamespace(arm_transfer=SimpleNamespace(source="source", target="target", commissioning=True))
    open_carry(g)
    assert seen == [False]  # no token file: automatic mode, whatever the grant says
    _token(token)
    open_carry(g)
    assert seen == [False, True] and not token.exists()  # consumed on use
    open_carry(g)
    assert seen == [False, True, False]
    with pytest.raises(CarryRefused):  # a pair without a reviewed library never consumes a token
        _token(token)
        open_carry(SimpleNamespace(arm_transfer=SimpleNamespace(source="x", target="y")))
    assert token.exists()
