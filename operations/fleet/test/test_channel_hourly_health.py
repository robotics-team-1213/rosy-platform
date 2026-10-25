"""Scheduled health uses only trusted cache and a durable, once-only channel slot."""
import asyncio
import json
from datetime import datetime
import sqlite3
import threading
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
import httpx

from fleet.server.channel.health import BareDiscordPublisher
from fleet.server.channel.requests import ChannelConfig
from fleet.server.channel.health import HourlyHealth


GUILD, CHANNEL, OTHER_CHANNEL, BOT = ("100000000000000000", "100000000000000001",
                                      "100000000000000002", "100000000000000003")
KST = ZoneInfo("Asia/Seoul")


@pytest.mark.parametrize("field", ["channel_id", "bot_id"])
@pytest.mark.parametrize("value", ["abc", "1" * 16, "1" * 21, 123])
def test_bare_publisher_rejects_invalid_destination_before_network(field, value):
    values = dict(guild_id=GUILD, channel_id=CHANNEL, bot_id=BOT, token="token", http=None)
    values[field] = value
    with pytest.raises(ValueError, match="destination"):
        BareDiscordPublisher(**values)


def config(*, enabled=True, channel=CHANNEL):
    return ChannelConfig(guild_id=GUILD, channel_id=channel, bot_id=BOT,
                         transport_key="k" * 40, users={"100000000000000004": "operator"},
                         hourly_health_enabled=enabled)


class FakeSender:
    def __init__(self, result=None, *, entered=None, release=None):
        self.result = result or {"state": "SENT", "provider_id": "100000000000000005"}
        self.entered, self.release, self.calls = entered, release, []
        self.scope = (GUILD, CHANNEL, BOT)

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


def hourly(tmp_path, now, rows, *, sender=None, enabled=True, ai=None):
    db = tmp_path / "fleet.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS fleet_tasks (status TEXT NOT NULL)")
        conn.executemany("INSERT INTO fleet_tasks VALUES (?)", [("RUNNING",), ("HOLD",), ("UNKNOWN",)])
    mono = [500.0]
    console = FakeConsole(["pinky-01", "pinky-02", "pinky-03"], mono=mono)
    gather = FakeGather(rows, captured_at=now)
    ai = ai or SimpleNamespace(status=lambda: {"state": "absent", "owner_mode": None, "age_s": None})
    journal = SimpleNamespace(config=config(enabled=enabled), _connect=lambda: sqlite3.connect(db))
    sender = sender or FakeSender()
    health = HourlyHealth(journal, sender, gather, console, ai, clock=lambda: now)
    return health, journal, sender, mono


def at(hour, minute=0, second=0):
    return datetime(2026, 10, 12, hour, minute, second, tzinfo=KST).timestamp()


def render(health, now=None):
    now = health.clock() if now is None else now
    return health.report(now, health.task_counts())


def test_report_uses_cached_per_robot_freshness_and_only_observed_sensor_values(tmp_path):
    now = at(9)
    rows = [
        {"robot_id": "pinky-01", "online": True, "_state_mono": 499.5,
         "state": {"safety": {"estop": False}, "battery": {"percent": 0},
                   "evidence": {"safety": {"evidence": "fresh"}, "battery": {"evidence": "fresh"}}}},
        {"robot_id": "pinky-02", "online": True, "_state_mono": 490,
         "state": {"safety": {"estop": False}, "battery": {"percent": 91},
                   "evidence": {"safety": {"evidence": "fresh"}, "battery": {"evidence": "stale"}}}},
    ]
    health, _, _, _ = hourly(tmp_path, now, rows,
                            ai=SimpleNamespace(status=lambda: {"state": "present", "owner_mode": "owner_busy",
                                                               "age_s": 0.8}))

    report = render(health)

    assert "pinky-01" in report and "0%" in report and "E-stop \ud574\uc81c" in report
    assert "pinky-02: \ubbf8\ud655\uc778" in report and "pinky-03: \ubbf8\ud655\uc778" in report
    assert "\uc791\uc5c5 \uc9c4\ud589 1 | HOLD 1 | UNKNOWN 1" in report
    assert "AI \uad00\uce21\uae30 present | owner_busy" in report
    assert "\ubaa8\ub378 admission: \ubbf8\ud655\uc778" in report
    assert "91%" not in report and "request_json" not in report

    health.ai.status = lambda: {"state": "absent", "owner_mode": "available", "age_s": 6.0}
    assert "AI \uad00\uce21\uae30 absent | \ubbf8\ud655\uc778" in render(health)


def test_report_marks_missing_or_stale_collection_unknown(tmp_path):
    now = at(9)
    health, _, _, _ = hourly(tmp_path, now, [], enabled=True)
    assert "\uc218\uc9d1 recent" in render(health)
    health.gather.gathered_at = 0
    health.gather._snapshot = None
    assert "\uc218\uc9d1 \ubbf8\ud655\uc778 | \uad00\uce21 \ubbf8\ud655\uc778" in render(health)
    assert "pinky-01: \ubbf8\ud655\uc778" in render(health)



def test_report_bounds_large_roster_and_discloses_omitted_robots(tmp_path):
    now = at(9)
    health, _, _, _ = hourly(tmp_path, now, [])
    health.console._robots = [f"robot-{index:03}-" + "x" * 80 for index in range(100)]
    report = render(health)
    assert len(report) <= 2000
    assert "100" in report and "\uc0dd\ub7b5" in report


def test_report_rejects_default_and_stale_safety_or_battery_facts(tmp_path):
    now = at(9)
    rows = [{"robot_id": "pinky-01", "online": True, "_state_mono": 499.5,
             "state": {"safety": {"estop": False}, "battery": {"percent": 0},
                       "evidence": {"safety": {"evidence": "unavailable"},
                                    "battery": {"evidence": "stale"}}}}]
    health, _, _, _ = hourly(tmp_path, now, rows)
    report = render(health)
    assert "0%" not in report
    assert "E-stop released" not in report
    assert "\ubc30\ud130\ub9ac \ubbf8\ud655\uc778" in report


def test_slow_task_count_read_does_not_block_event_loop(tmp_path):
    now = at(9)
    health, _, _, _ = hourly(tmp_path, now, [])
    loop_thread = threading.get_ident()
    entered, release, responsive = threading.Event(), threading.Event(), threading.Event()
    reader_threads = []
    read_counts = health.task_counts

    def blocked_read():
        reader_threads.append(threading.get_ident())
        entered.set()
        if reader_threads[-1] != loop_thread:
            release.wait()
            assert responsive.is_set()
        return read_counts()

    health.task_counts = blocked_read

    async def run():
        loop = asyncio.get_running_loop()

        def unblock_from_loop():
            responsive.set()
            release.set()

        def schedule_unblock():
            entered.wait()
            loop.call_soon_threadsafe(unblock_from_loop)

        controller = threading.Thread(target=schedule_unblock)
        controller.start()
        await health.run_once()
        controller.join()

    asyncio.run(run())
    assert reader_threads and reader_threads[0] != loop_thread


def test_two_workers_share_one_durable_claim_and_nonce(tmp_path):
    now, entered, release = at(9), asyncio.Event(), asyncio.Event()
    sender = FakeSender(entered=entered, release=release)
    first, _, _, _ = hourly(tmp_path, now, [], sender=sender)
    second, _, _, _ = hourly(tmp_path, now, [], sender=sender)

    async def run():
        owner = asyncio.create_task(first.run_once())
        await entered.wait()
        second.recover(now)
        await second.run_once()
        release.set()
        await owner
    asyncio.run(run())

    assert len(sender.calls) == 1
    assert len(sender.calls[0][0]) == 24
    with sqlite3.connect(tmp_path / "fleet.sqlite3") as conn:
        state, nonce = conn.execute("SELECT state, nonce FROM fleet_channel_hourly_health").fetchone()
    assert (state, nonce) == ("SENT", sender.calls[0][0])



def test_startup_recovery_does_not_clobber_a_live_worker_claim(tmp_path):
    now, entered, release = at(9), asyncio.Event(), asyncio.Event()
    sender = FakeSender(entered=entered, release=release)
    first, journal, _, _ = hourly(tmp_path, now, [], sender=sender)
    second, _, _, _ = hourly(tmp_path, now, [], sender=sender)

    async def run():
        owner = asyncio.create_task(first.run_once())
        await entered.wait()
        second.recover(now)
        await second.run_once()
        release.set()
        await owner
    asyncio.run(run())

    with sqlite3.connect(tmp_path / "fleet.sqlite3") as conn:
        assert conn.execute("SELECT state FROM fleet_channel_hourly_health").fetchone()[0] == "SENT"
    assert len(sender.calls) == 1


def test_late_confirmed_send_is_recorded_after_recovery_without_replay(tmp_path):
    now, entered, release = at(9), asyncio.Event(), asyncio.Event()
    provider_id = "100000000000000005"
    sender = FakeSender({"state": "SENT", "provider_id": provider_id},
                        entered=entered, release=release)
    first, journal, _, _ = hourly(tmp_path, now, [], sender=sender)
    second, _, _, _ = hourly(tmp_path, now, [], sender=sender)

    async def run():
        owner = asyncio.create_task(first.run_once())
        await entered.wait()
        second.recover(now + 31)
        release.set()
        await owner
        await second.run_once()
    asyncio.run(run())

    assert len(sender.calls) == 1
    with sqlite3.connect(tmp_path / "fleet.sqlite3") as conn:
        assert conn.execute("SELECT state, provider_id, attempts FROM fleet_channel_hourly_health").fetchone() == (
            "SENT", provider_id, 1)


def test_mid_hour_start_skips_slot_without_backlog_then_sends_next_boundary(tmp_path):
    health, _, sender, _ = hourly(tmp_path, at(9, 0, 1), [])
    health.task_counts = lambda: pytest.fail("off-hour scans must not build a health report")
    asyncio.run(health.run_once())
    assert sender.calls == []
    with sqlite3.connect(tmp_path / "fleet.sqlite3") as conn:
        assert conn.execute("SELECT state FROM fleet_channel_hourly_health").fetchone()[0] == "SKIPPED"

    health.clock = lambda: at(10)
    health.task_counts = lambda: {"RUNNING": 1, "HOLD": 0, "UNKNOWN": 0}
    asyncio.run(health.run_once())
    assert len(sender.calls) == 1
    assert "KST 10:00" in sender.calls[0][1]


def test_only_known_rate_limit_retries_inside_the_bounded_window(tmp_path):
    now = [at(9)]
    sender = FakeSender({"state": "RETRY", "provider_id": None})
    health, _, _, _ = hourly(tmp_path, now[0], [], sender=sender)
    health.clock = lambda: now[0]

    asyncio.run(health.run_once())
    first_payload = sender.calls[0][1]
    health.gather.gathered_at = 0
    health.gather._snapshot = None
    now[0] += 15
    asyncio.run(health.run_once())
    assert sender.calls[1][1] == first_payload
    now[0] += 15
    sender.result = {"state": "SENT", "provider_id": "100000000000000005"}
    asyncio.run(health.run_once())

    assert len(sender.calls) == 3
    assert len({nonce for nonce, _ in sender.calls}) == 1
    with sqlite3.connect(tmp_path / "fleet.sqlite3") as conn:
        assert conn.execute("SELECT state, attempts FROM fleet_channel_hourly_health").fetchone() == ("SENT", 3)


def test_restart_after_claim_is_unknown_and_never_replayed(tmp_path):
    now = at(9)
    health, journal, sender, _ = hourly(tmp_path, now, [])
    claim = health.claim(now)
    assert claim is not None

    restarted = HourlyHealth(journal, sender, health.gather, health.console, health.ai,
                             clock=lambda: now)
    restarted.recover(now + 31)
    restarted.clock = lambda: now + 31
    asyncio.run(restarted.run_once())

    assert sender.calls == []
    with sqlite3.connect(tmp_path / "fleet.sqlite3") as conn:
        assert conn.execute("SELECT state FROM fleet_channel_hourly_health").fetchone()[0] == "UNKNOWN"


def test_route_change_during_publish_is_unknown_and_cannot_replay_to_new_channel(tmp_path):
    now, release = at(9), asyncio.Event()
    sender = FakeSender(release=release)
    health, journal, _, _ = hourly(tmp_path, now, [], sender=sender)
    async def run():
        sending = asyncio.create_task(health.run_once())
        while not sender.calls:
            await asyncio.sleep(0)
        journal.config = config(channel=OTHER_CHANNEL)
        release.set()
        await sending
        await health.run_once()
    asyncio.run(run())

    assert len(sender.calls) == 1
    with sqlite3.connect(tmp_path / "fleet.sqlite3") as conn:
        assert conn.execute("SELECT state FROM fleet_channel_hourly_health").fetchone()[0] == "UNKNOWN"



def test_publisher_route_must_match_the_durable_claim_scope(tmp_path):
    now = at(9)
    health, journal, sender, _ = hourly(tmp_path, now, [])
    journal.config = config(channel=OTHER_CHANNEL)
    asyncio.run(health.run_once())
    assert sender.calls == []
    with sqlite3.connect(tmp_path / "fleet.sqlite3") as conn:
        state, channel = conn.execute(
            "SELECT state, channel_id FROM fleet_channel_hourly_health").fetchone()
    assert (state, channel) == ("FAILED", OTHER_CHANNEL)


def test_unknown_delivery_is_terminal_even_after_time_jump(tmp_path):
    now = [at(9)]
    sender = FakeSender({"state": "UNKNOWN", "provider_id": None})
    health, _, _, _ = hourly(tmp_path, now[0], [], sender=sender)
    health.clock = lambda: now[0]

    asyncio.run(health.run_once())
    now[0] += 60
    asyncio.run(health.run_once())

    assert len(sender.calls) == 1
    with sqlite3.connect(tmp_path / "fleet.sqlite3") as conn:
        assert conn.execute("SELECT state FROM fleet_channel_hourly_health").fetchone()[0] == "UNKNOWN"


def test_clock_rewind_cannot_repeat_a_sent_hour_and_forward_jump_skips_backlog(tmp_path):
    now = [at(9)]
    health, _, sender, _ = hourly(tmp_path, now[0], [])
    health.clock = lambda: now[0]

    asyncio.run(health.run_once())
    now[0] -= 120
    asyncio.run(health.run_once())
    now[0] = at(10, 0, 20)
    asyncio.run(health.run_once())

    assert len(sender.calls) == 1
    with sqlite3.connect(tmp_path / "fleet.sqlite3") as conn:
        states = [state for (state,) in conn.execute(
            "SELECT state FROM fleet_channel_hourly_health ORDER BY slot")]
        assert states.count("SENT") == 1
        assert states.count("SKIPPED") == 2



def test_bare_publisher_uses_fixed_channel_nonce_and_validates_provider_readback():
    nonce = "b" * 24

    async def run(handler):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            publisher = BareDiscordPublisher(guild_id=GUILD, channel_id=CHANNEL, bot_id=BOT,
                                             token="test-bot-token", http=http)
            return await publisher.publish(nonce=nonce, content="ROSY Fleet health")

    def accepted(request):
        payload = json.loads(request.content)
        assert str(request.url) == f"https://discord.com/api/v10/channels/{CHANNEL}/messages"
        assert request.headers["Authorization"] == "Bot test-bot-token"
        assert "message_reference" not in payload and "flags" not in payload
        assert payload["nonce"] == nonce and payload["enforce_nonce"] is True
        assert payload["allowed_mentions"] == {"parse": [], "replied_user": False}
        return httpx.Response(200, json={"id": "100000000000000005", "nonce": nonce,
                                         "channel_id": CHANNEL,
                                         "author": {"id": BOT, "bot": True}})

    assert asyncio.run(run(accepted)) == {"state": "SENT", "provider_id": "100000000000000005"}
    wrong_route = lambda request: httpx.Response(200, json={
        "id": "100000000000000005", "nonce": nonce, "channel_id": OTHER_CHANNEL,
        "author": {"id": BOT, "bot": True}})
    assert asyncio.run(run(wrong_route))["state"] == "UNKNOWN"


@pytest.mark.parametrize("status,state", [(429, "RETRY"), (403, "FAILED"), (500, "UNKNOWN")])
def test_bare_publisher_retries_only_known_rate_limit_or_connection(status, state):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda request: httpx.Response(status, json={}))) as http:
            publisher = BareDiscordPublisher(guild_id=GUILD, channel_id=CHANNEL, bot_id=BOT,
                                             token="test-bot-token", http=http)
            return await publisher.publish(nonce="c" * 24, content="status")
    assert asyncio.run(run())["state"] == state


def test_bare_publisher_does_not_retry_ambiguous_read_timeout():
    def handler(request):
        raise httpx.ReadTimeout("response was lost", request=request)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            publisher = BareDiscordPublisher(guild_id=GUILD, channel_id=CHANNEL, bot_id=BOT,
                                             token="test-bot-token", http=http)
            return await publisher.publish(nonce="d" * 24, content="status")
    assert asyncio.run(run()) == {"state": "UNKNOWN", "provider_id": None}
