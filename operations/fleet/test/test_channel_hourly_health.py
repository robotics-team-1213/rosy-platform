"""Scheduled health uses only trusted cache and a durable, once-only channel slot."""
import asyncio
from datetime import datetime, timezone
import sqlite3
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from fleet.server.channel.requests import ChannelConfig
from fleet.server.channel.hourly_health import HourlyHealth


GUILD, CHANNEL, OTHER_CHANNEL, BOT = ("100000000000000000", "100000000000000001",
                                      "100000000000000002", "100000000000000003")
KST = ZoneInfo("Asia/Seoul")


def config(*, enabled=True, channel=CHANNEL):
    return ChannelConfig(guild_id=GUILD, channel_id=channel, bot_id=BOT,
                         transport_key="k" * 40, users={"100000000000000004": "operator"},
                         hourly_health_enabled=enabled)


class FakeSender:
    def __init__(self, result=None, *, entered=None, release=None):
        self.result = result or {"state": "SENT", "provider_id": "100000000000000005"}
        self.entered, self.release, self.calls = entered, release, []

    async def publish(self, *, nonce, content):
        self.calls.append((nonce, content))
        if self.entered:
            self.entered.set()
        if self.release:
            await self.release.wait()
        return self.result


class FakeConsole:
    def __init__(self, robots, *, mono):
        self._robots, self._mono = robots, mono

    def clients(self):
        return {robot: object() for robot in self._robots}

    def _clock(self):
        return self._mono[0]


class FakeGather:
    def __init__(self, rows, *, captured_at):
        self._snapshot = {"robots": rows}
        self.gathered_at = captured_at

    async def __call__(self):
        pytest.fail("hourly health must not force a Fleet gather")


def setup(tmp_path, now, rows, *, sender=None, enabled=True, ai=None):
    db = tmp_path / "fleet.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE fleet_tasks (status TEXT NOT NULL)")
        conn.executemany("INSERT INTO fleet_tasks VALUES (?)", [("RUNNING",), ("HOLD",), ("UNKNOWN",)])
    mono = [500.0]
    console = FakeConsole(["pinky-01", "pinky-02", "pinky-03"], mono=mono)
    gather = FakeGather(rows, captured_at=now)
    ai = ai or SimpleNamespace(status=lambda: {"state": "absent", "owner_mode": None, "age_s": None})
    journal = SimpleNamespace(config=config(enabled=enabled))
    sender = sender or FakeSender()
    health = HourlyHealth(db, journal, sender, gather, console, ai, clock=lambda: now)
    return health, journal, sender, mono


def at(hour, minute=0, second=0):
    return datetime(2026, 10, 12, hour, minute, second, tzinfo=KST).timestamp()


@pytest.mark.asyncio
async def test_report_uses_cached_per_robot_freshness_and_only_observed_sensor_values(tmp_path):
    now = at(9)
    rows = [
        {"robot_id": "pinky-01", "online": True, "_state_mono": 499.5,
         "state": {"safety": {"estop": False}, "battery": {"percent": 0}}},
        {"robot_id": "pinky-02", "online": True, "_state_mono": 490,
         "state": {"safety": {"estop": False}, "battery": {"percent": 91}}},
    ]
    health, _, _, _ = setup(tmp_path, now, rows,
                            ai=SimpleNamespace(status=lambda: {"state": "present", "owner_mode": "owner_busy",
                                                               "age_s": 0.8}))

    report = health.report()

    assert "pinky-01" in report and "0%" in report and "E-stop 해제 관측" in report
    assert "pinky-02" in report and "미확인" in report
    assert "pinky-03" in report and "미확인" in report
    assert "진행 1 · HOLD 1 · UNKNOWN 1" in report
    assert "AI 관측기 heartbeat: present · owner_busy" in report
    assert "모델 admission: 미확인" in report
    assert "91%" not in report and "request_json" not in report


@pytest.mark.asyncio
async def test_two_workers_share_one_durable_claim_and_nonce(tmp_path):
    now, entered, release = at(9), asyncio.Event(), asyncio.Event()
    sender = FakeSender(entered=entered, release=release)
    first, _, _, _ = setup(tmp_path, now, [], sender=sender)
    second, _, _, _ = setup(tmp_path, now, [], sender=sender)

    owner = asyncio.create_task(first.run_once())
    await entered.wait()
    await second.run_once()
    release.set()
    await owner

    assert len(sender.calls) == 1
    assert len(sender.calls[0][0]) == 24
    with sqlite3.connect(tmp_path / "fleet.sqlite3") as conn:
        state, nonce = conn.execute("SELECT state, nonce FROM fleet_channel_hourly_health").fetchone()
    assert (state, nonce) == ("SENT", sender.calls[0][0])


@pytest.mark.asyncio
async def test_mid_hour_start_skips_slot_without_backlog_then_sends_next_boundary(tmp_path):
    health, _, sender, _ = setup(tmp_path, at(9, 0, 21), [])
    await health.run_once()
    assert sender.calls == []
    with sqlite3.connect(tmp_path / "fleet.sqlite3") as conn:
        assert conn.execute("SELECT state FROM fleet_channel_hourly_health").fetchone()[0] == "SKIPPED"

    health.clock = lambda: at(10)
    await health.run_once()
    assert len(sender.calls) == 1
    assert "KST 10:00" in sender.calls[0][1]


@pytest.mark.asyncio
async def test_only_known_rate_limit_retries_inside_the_bounded_window(tmp_path):
    now = [at(9)]
    sender = FakeSender({"state": "RETRY", "provider_id": None})
    health, _, _, _ = setup(tmp_path, now[0], [], sender=sender)
    health.clock = lambda: now[0]

    await health.run_once()
    now[0] += 15
    await health.run_once()
    now[0] += 15
    sender.result = {"state": "SENT", "provider_id": "100000000000000005"}
    await health.run_once()

    assert len(sender.calls) == 3
    assert len({nonce for nonce, _ in sender.calls}) == 1
    with sqlite3.connect(tmp_path / "fleet.sqlite3") as conn:
        assert conn.execute("SELECT state, attempts FROM fleet_channel_hourly_health").fetchone() == ("SENT", 3)


@pytest.mark.asyncio
async def test_restart_after_claim_is_unknown_and_never_replayed(tmp_path):
    now = at(9)
    health, journal, sender, _ = setup(tmp_path, now, [])
    claim = health.claim(now)
    assert claim["state"] == "CLAIMED"

    restarted = HourlyHealth(health.path, journal, sender, health.gather, health.console, health.ai,
                             clock=lambda: now)
    restarted.recover()
    await restarted.run_once()

    assert sender.calls == []
    with sqlite3.connect(tmp_path / "fleet.sqlite3") as conn:
        assert conn.execute("SELECT state FROM fleet_channel_hourly_health").fetchone()[0] == "UNKNOWN"


@pytest.mark.asyncio
async def test_route_change_during_publish_is_unknown_and_cannot_replay_to_new_channel(tmp_path):
    now, release = at(9), asyncio.Event()
    sender = FakeSender(release=release)
    health, journal, _, _ = setup(tmp_path, now, [], sender=sender)
    sending = asyncio.create_task(health.run_once())
    while not sender.calls:
        await asyncio.sleep(0)
    journal.config = config(channel=OTHER_CHANNEL)
    release.set()
    await sending
    await health.run_once()

    assert len(sender.calls) == 1
    with sqlite3.connect(tmp_path / "fleet.sqlite3") as conn:
        assert conn.execute("SELECT state FROM fleet_channel_hourly_health").fetchone()[0] == "UNKNOWN"


@pytest.mark.asyncio
async def test_unknown_delivery_is_terminal_even_after_time_jump(tmp_path):
    now = [at(9)]
    sender = FakeSender({"state": "UNKNOWN", "provider_id": None})
    health, _, _, _ = setup(tmp_path, now[0], [], sender=sender)
    health.clock = lambda: now[0]

    await health.run_once()
    now[0] += 60
    await health.run_once()

    assert len(sender.calls) == 1
    with sqlite3.connect(tmp_path / "fleet.sqlite3") as conn:
        assert conn.execute("SELECT state FROM fleet_channel_hourly_health").fetchone()[0] == "UNKNOWN"

