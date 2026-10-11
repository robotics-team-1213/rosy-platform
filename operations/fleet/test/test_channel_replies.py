"""Reply claims survive restart without replaying ambiguous delivery."""
from contextlib import closing

from core_common.protocol.channel_requests import DiscordRequestEnvelope
from fleet.server.channel_replies import ChannelReplyOutbox
from fleet.server.channel_requests import ChannelConfig, ChannelRequests


GUILD, CHANNEL, USER, BOT, MESSAGE = (str(100000000000000000 + i) for i in range(5))


def fixture(tmp_path):
    accounts = {"op": "operator"}
    config = ChannelConfig(guild_id=GUILD, channel_id=CHANNEL, bot_id=BOT,
                           transport_key="test-key-" * 5, users={USER: "op"})
    journal = ChannelRequests(tmp_path / "tasks.sqlite", config, accounts)
    outbox = ChannelReplyOutbox(journal, clock=lambda: 1000)
    journal.reply_outbox = outbox
    envelope = DiscordRequestEnvelope(guild_id=GUILD, channel_id=CHANNEL, author_id=USER,
                                      message_id=MESSAGE, mentions=[BOT], author_bot=False,
                                      webhook_id=None, content=f"<@{BOT}> inspect")
    return journal, outbox, accounts, envelope


def test_receipt_and_reply_are_atomic_and_duplicate_intake_is_one_reply(tmp_path):
    journal, outbox, _, envelope = fixture(tmp_path)
    receipt = journal.receive(envelope)
    assert journal.receive(envelope) == receipt
    row = outbox.claim(now=1000)
    assert row["request_id"] == receipt["request_id"]
    assert row["message_id"] == MESSAGE
    assert row["kind"] == "RECEIVED" and row["attempts"] == 1
    assert "inspect" not in row["content"]
    assert outbox.claim(now=1001) is None
    outbox.finish(row, state="SENT", provider_id=USER, now=1002)
    assert outbox.rows("op")[0]["state"] == "SENT"
    assert outbox.claim(now=1040) is None


def test_process_restart_marks_sending_unknown_without_replay(tmp_path):
    journal, outbox, _, envelope = fixture(tmp_path)
    journal.receive(envelope)
    row = outbox.claim(now=1000)
    restarted = ChannelReplyOutbox(journal)
    assert restarted.claim(now=1031) is None
    assert restarted.rows("op")[0]["state"] == "UNKNOWN"
    # A late completion cannot overwrite a recovered unknown attempt.
    restarted.finish(row, state="SENT", provider_id=USER, now=1032)
    assert restarted.rows("op")[0]["state"] == "UNKNOWN"


def test_known_retry_is_bounded_and_fenced(tmp_path):
    journal, outbox, _, envelope = fixture(tmp_path)
    journal.receive(envelope)
    for now in (1000, 1060, 1120):
        row = outbox.claim(now=now)
        assert row is not None
        outbox.finish(row, state="RETRY", provider_id=None, now=now)
    assert outbox.claim(now=1180) is None
    assert outbox.rows("op")[0]["state"] == "FAILED"


def test_current_account_and_identity_mapping_are_checked_before_claim(tmp_path):
    journal, outbox, accounts, envelope = fixture(tmp_path)
    journal.receive(envelope)
    accounts["op"] = "viewer"
    assert outbox.claim(now=1000) is None
    with closing(journal._connect()) as conn:
        assert conn.execute("SELECT state FROM fleet_channel_reply_outbox").fetchone()[0] == "SUPERSEDED"


def test_queue_failure_rolls_back_receipt(tmp_path, monkeypatch):
    journal, outbox, _, envelope = fixture(tmp_path)
    def unavailable(*args):
        raise OSError("journal unavailable")
    monkeypatch.setattr(outbox, "received", unavailable)
    try:
        journal.receive(envelope)
    except OSError:
        pass
    else:
        raise AssertionError("reply journal failure was ignored")
    assert journal.read("op") == []
