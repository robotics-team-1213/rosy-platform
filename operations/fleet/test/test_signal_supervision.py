"""D-443 safety regressions: supervision gaps, bounded recovery and evidence."""

import asyncio
from hashlib import sha256

import pytest

from fake_signals import FakeSignal, observed_body
from fastapi.testclient import TestClient
from fleet.server.app import create_app
from fleet.server.console import FleetConsole
from fleet.server.signal_config import SignalEndpoint
from fleet.server.signals import SignalApiError, SignalConsole, cross_check


def console_for(signal, now):
    return SignalConsole([SignalEndpoint(signal.signal_id, "http://127.0.0.1:9081", "test")],
                         [signal], clock=lambda: now[0])


def test_absent_observation_is_not_measured_agreement():
    lamps = {"red": True, "yellow": False, "green": False}
    assert cross_check(lamps, lamps, None)[0] == "absent"


def test_pending_observation_is_not_measured_agreement():
    lamps = {"red": True, "yellow": False, "green": False}
    assert cross_check(lamps, lamps, observed_body(pending=True),
                       lamp_to_roi={"red": "left"})[0] == "pending"


def test_unknown_measurement_is_not_agreement_with_an_off_lamp():
    lamps = {"red": False, "yellow": False, "green": False}
    observed = observed_body()
    observed["stable"]["left"] = {"lit": None, "group": None, "pending": False}
    assert cross_check(None, lamps, observed, lamp_to_roi={"red": "left"})[0] == "unknown"


def test_poll_resyncs_seq_from_device_last_seq():
    signal = FakeSignal("signal_1")
    signal.mode = "all_red"
    signal.last_seq = 99
    console = console_for(signal, [0.0])
    asyncio.run(console.poll_once())
    asyncio.run(console.command(signal.signal_id, {"mode": "cycle"}))
    assert signal.commands == [{"mode": "cycle", "seq": 100}]


@pytest.mark.parametrize("mode", ["all_red", "flash_red"])
def test_safe_command_after_fleet_restart_retries_once_after_resync(mode):
    signal = FakeSignal("signal_1")
    signal.last_seq = 99
    console = console_for(signal, [0.0])
    row = asyncio.run(console.command(signal.signal_id, {"mode": mode}))
    assert row["mismatch"] is None
    assert signal.commands == [{"mode": mode, "seq": 100}]


def test_non_safety_verb_is_not_retried_after_stale_seq():
    signal = FakeSignal("signal_1")
    signal.last_seq = 99
    console = console_for(signal, [0.0])
    row = asyncio.run(console.command(signal.signal_id, {"mode": "cycle"}))
    assert row["mismatch"] == "stale_seq"
    assert signal.commands == []


def test_safe_retry_budget_is_one_even_when_device_keeps_advancing():
    signal = FakeSignal("signal_1")
    attempts = []

    async def refuse(body):
        attempts.append(body)
        raise SignalApiError(signal.signal_id, 409, "stale_seq", "ahead", body["seq"] + 10)

    signal.command = refuse
    console = console_for(signal, [0.0])
    row = asyncio.run(console.command(signal.signal_id, {"mode": "all_red"}))
    assert row["mismatch"] == "stale_seq"
    assert [body["seq"] for body in attempts] == [1, 12]


def test_client_body_cannot_override_supervisor_seq():
    signal = FakeSignal("signal_1")
    console = console_for(signal, [0.0])
    asyncio.run(console.command(signal.signal_id, {"mode": "cycle", "seq": 999}))
    assert signal.commands[0]["seq"] == 1


def test_supervision_gap_latches_old_intent_until_a_fresh_operator_command():
    signal = FakeSignal("signal_1")
    now = [0.0]
    console = console_for(signal, now)
    asyncio.run(console.command(signal.signal_id, {"mode": "cycle"}))
    signal.mode = "failsafe"
    now[0] = 10.0
    asyncio.run(console.poll_once())
    now[0] = 12.0
    asyncio.run(console.poll_once())
    assert signal.commands == [{"mode": "cycle", "seq": 1}]
    assert console.snapshot()[signal.signal_id]["requires_command"] is True
    asyncio.run(console.command(signal.signal_id, {"mode": "cycle"}))
    assert console.snapshot()[signal.signal_id]["requires_command"] is False


def test_one_poll_failure_does_not_erase_a_continuous_supervision_interval():
    signal = FakeSignal("signal_1")
    now = [0.0]
    console = console_for(signal, now)
    asyncio.run(console.command(signal.signal_id, {"mode": "cycle"}))
    now[0] = 2.0
    signal.status_error = ConnectionError("transient")
    asyncio.run(console.poll_once())
    now[0] = 4.0
    signal.status_error = None
    signal.mode = "failsafe"
    asyncio.run(console.poll_once())
    assert [body["mode"] for body in signal.commands] == ["cycle", "cycle"]


def test_offline_row_carries_link_and_age_without_calling_it_fresh():
    signal = FakeSignal("signal_1")
    now = [0.0]
    console = console_for(signal, now)
    asyncio.run(console.poll_once())
    signal.status_error = ConnectionError("offline")
    now[0] = 7.0
    asyncio.run(console.poll_once())
    row = console.snapshot()[signal.signal_id]
    assert row["online"] is False
    assert row["mode"] == "flash_red"  # last device report survives for display
    assert row["link"] == "unreachable"
    assert row["age_s"] == 7.0


def test_fresh_operator_command_after_gap_is_not_stale_itself():
    signal = FakeSignal("signal_1")
    now = [0.0]
    console = console_for(signal, now)
    asyncio.run(console.command(signal.signal_id, {"mode": "cycle"}))
    now[0] = 20.0
    asyncio.run(console.command(signal.signal_id, {"mode": "cycle"}))
    assert console.snapshot()[signal.signal_id]["requires_command"] is False


def test_manual_aspect_drops_to_flash_red_when_operator_presence_lapses():
    signal = FakeSignal("signal_1")
    now = [0.0]
    console = console_for(signal, now)
    asyncio.run(console.command(signal.signal_id, {
        "mode": "manual", "lamps": {"red": False, "yellow": False, "green": True}}, actor="op"))
    for second in range(2, 11, 2):
        now[0] = float(second)
        asyncio.run(console.poll_once())
    assert [body["mode"] for body in signal.commands] == ["manual", "flash_red"]
    row = console.snapshot()[signal.signal_id]
    assert row["requires_command"] is True
    assert row["intent"]["mode"] == "manual"
    assert row["intent_age_s"] == 10.0
    console.operator_presence("op")
    signal.mode = "failsafe"
    now[0] = 12.0
    asyncio.run(console.poll_once())
    assert [body["mode"] for body in signal.commands] == ["manual", "flash_red"]


def test_manual_reassert_needs_presence_even_while_supervision_continues():
    signal = FakeSignal("signal_1")
    now = [0.0]
    console = console_for(signal, now)
    asyncio.run(console.command(signal.signal_id, {"mode": "manual"}, actor="op"))
    for second in (2.0, 4.0, 6.0, 8.0):
        now[0] = second
        asyncio.run(console.poll_once())
    signal.mode = "failsafe"
    now[0] = 10.0
    asyncio.run(console.poll_once())
    assert [body["mode"] for body in signal.commands] == ["manual"]
    assert console.snapshot()[signal.signal_id]["requires_command"] is True


def test_cycle_intent_does_not_require_operator_presence():
    signal = FakeSignal("signal_1")
    now = [0.0]
    console = console_for(signal, now)
    asyncio.run(console.command(signal.signal_id, {"mode": "cycle"}))
    for second in range(2, 15, 2):
        now[0] = float(second)
        asyncio.run(console.poll_once())
    signal.mode = "failsafe"
    now[0] = 16.0
    asyncio.run(console.poll_once())
    assert [body["mode"] for body in signal.commands] == ["cycle", "cycle"]


def test_concurrent_commands_get_distinct_monotonic_seq():
    signal = FakeSignal("signal_1")
    console = console_for(signal, [0.0])
    original = signal.command
    entered = asyncio.Event()
    proceed = asyncio.Event()

    async def pause_first(body):
        if not entered.is_set():
            entered.set()
            await proceed.wait()
        return await original(body)

    signal.command = pause_first

    async def scenario():
        first = asyncio.create_task(console.command(signal.signal_id, {"mode": "cycle"}))
        await entered.wait()
        second = asyncio.create_task(console.command(signal.signal_id, {"mode": "all_red"}))
        proceed.set()
        await asyncio.gather(first, second)

    asyncio.run(scenario())
    assert [body["seq"] for body in signal.commands] == [1, 2]


def test_presence_requires_operator_and_viewer_reads_do_not_renew_it(tmp_path):
    from fleet.server.task_service import FleetTaskService
    from fleet.server.task_store import FleetTaskStore
    signal = FakeSignal("signal_1")
    now = [0.0]
    signals = console_for(signal, now)
    tasks = FleetTaskService(FleetTaskStore(tmp_path / "tasks.sqlite"), robot_ids=())
    client = TestClient(create_app(FleetConsole([], [], signal_console=signals), task_service=tasks, site_users={
        sha256(b"op-token").hexdigest(): {"principal_id": "op", "role": "operator"},
        sha256(b"viewer-token").hexdigest(): {"principal_id": "viewer", "role": "viewer"},
    }))
    viewer = {"Authorization": "Bearer viewer-token"}
    operator = {"Authorization": "Bearer op-token"}
    assert client.post("/api/fleet/signals/presence", headers=viewer).status_code == 403
    assert client.post("/api/fleet/signals/presence", headers=operator).status_code == 200
    assert client.post("/api/fleet/signals/signal_1/command", headers=operator,
                       json={"mode": "manual"}).status_code == 200
    now[0] = 8.0
    assert client.get("/api/fleet/state", headers=viewer).status_code == 200
    now[0] = 10.0
    asyncio.run(signals.poll_once())
    assert signal.commands[-1]["mode"] == "flash_red"


def test_restart_does_not_keep_unowned_device_manual_lit():
    signal = FakeSignal("signal_1")
    signal.lamps = {"red": False, "yellow": False, "green": True}
    console = console_for(signal, [0.0])
    asyncio.run(console.poll_once())
    assert signal.commands == [{"mode": "flash_red", "seq": 1}]


def test_signals_are_supervised_without_console_requests_and_cancelled_on_shutdown():
    from threading import Event

    signal = FakeSignal("signal_1")
    signal.mode = "all_red"
    polled = Event()
    original = signal.status

    async def status():
        polled.set()
        return await original()

    signal.status = status
    signals = console_for(signal, [0.0])
    app = create_app(FleetConsole([], [], signal_console=signals))
    with TestClient(app):
        assert polled.wait(5), "supervision must not wait for a UI/API read"
        task = app.state.signal_supervision
        assert not task.done()
    assert task.cancelled()


def test_anonymous_fallback_cannot_create_presence_or_manual_aspect():
    signal = FakeSignal("signal_1")
    signals = console_for(signal, [0.0])
    client = TestClient(create_app(FleetConsole([], [], signal_console=signals)))
    for headers in ({}, {"Authorization": "Bearer unconfigured"}):
        assert client.post("/api/fleet/signals/presence", headers=headers).status_code == 401
        assert client.post("/api/fleet/signals/signal_1/command", headers=headers,
                           json={"mode": "manual"}).status_code == 401
    assert signal.commands == []


def test_queued_old_cycle_is_not_replayed_after_a_failed_safe_command():
    signal = FakeSignal("signal_1")
    console = console_for(signal, [0.0])
    attempts = []

    async def scenario():
        await console.command(signal.signal_id, {"mode": "cycle"})
        signal.mode = "failsafe"
        console._record(signal.signal_id, signal._status())
        entered, release, queued = asyncio.Event(), asyncio.Event(), asyncio.Event()
        original_device_command = signal.command
        original_command = console.command

        async def device_command(body):
            attempts.append(body)
            if body["mode"] == "all_red":
                entered.set()
                await release.wait()
                raise SignalApiError(signal.signal_id, 409, "stale_seq", "other writer", body["seq"] + 10)
            return await original_device_command(body)

        async def wrapped(*args, **kwargs):
            if kwargs.get("_restore_intent"):
                queued.set()
            return await original_command(*args, **kwargs)

        signal.command = device_command
        console.command = wrapped
        pending_stop = asyncio.create_task(console.command(signal.signal_id, {"mode": "all_red"}))
        await entered.wait()
        reassert = asyncio.create_task(console._reassert_failsafes())
        await queued.wait()
        release.set()
        await asyncio.gather(pending_stop, reassert)

    asyncio.run(scenario())
    assert [body["mode"] for body in attempts] == ["all_red", "all_red"]
    assert console.snapshot()[signal.signal_id]["mismatch"] == "stale_seq"
