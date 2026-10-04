"""Bounded, identity-checked owner recovery acknowledgements; never replay."""

import pytest

from fleet.server.local_stop_transport import UnixLocalStopTransport


def client(tmp_path, reply):
    transport = UnixLocalStopTransport(tmp_path)
    calls = []
    def exchange(instance_id, document):
        calls.append((instance_id, document))
        return reply
    transport._exchange = exchange
    return transport, calls


def reply():
    return {"version": 1, "status": 200, "workcell_id": "cell", "instance_id": "arm",
            "actor_id": "operator-a", "observed_sequence": 11,
            "decision": {"accepted": True, "state": "ready", "reason": "recovered"}}


def recover(transport):
    return transport.recover_owner(workcell_id="cell", instance_id="arm", actor_id="operator-a",
                                   authority_epoch=2, dispatch_generation=1,
                                   operator_confirmed=True, observed_sequence=11)


@pytest.mark.parametrize("patch", [{"version": True}, {"status": 200.0}, {"workcell_id": "other"},
                                   {"instance_id": "other"}, {"actor_id": "other"},
                                   {"observed_sequence": True}, {"observed_sequence": 10},
                                   {"decision": {"accepted": 1, "state": "ready", "reason": "recovered"}},
                                   {"decision": {"accepted": True, "state": "active", "reason": "recovered"}}])
def test_recovery_reply_requires_exact_types_identity_and_nonmoving_ready(tmp_path, patch):
    transport, calls = client(tmp_path, {**reply(), **patch})
    assert recover(transport)["status"] == 503
    assert len(calls) == 1


def test_missing_recovery_acknowledgement_is_not_replayed(tmp_path):
    transport, calls = client(tmp_path, None)
    assert recover(transport)["status"] == 503 and len(calls) == 1


def test_valid_reply_preserves_actor_readback_and_confirmation_frame(tmp_path):
    transport, calls = client(tmp_path, reply())
    assert recover(transport) == reply()
    assert calls[0][1]["operation"] == "RecoverOwner"
    assert calls[0][1]["operator_confirmed"] is True
    assert len(calls) == 1
