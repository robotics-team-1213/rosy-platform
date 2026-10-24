"""The Fleet UDS client frames neutral grants as v2 and binds their receipts."""
from core_common.protocol.schemas import FleetArmTransferGrant
from fleet.server.local_action_transport import LocalActionUnavailable, UnixLocalActionTransport
import pytest

from test_cell_action_transport import _grant as cell_grant, _response


def grant():
    raw = cell_grant().model_dump()
    raw.pop("cell_transfer")
    raw.update(action_kind="ARM_TRANSFER", arm_transfer=dict(
        object_ref="object-1", source="pose-1", target="pose-2", catalog_digest="a" * 64,
        bindings_digest="b" * 64, resource_policy_digest="c" * 64))
    return FleetArmTransferGrant.model_validate(raw)


@pytest.mark.parametrize("operation", ["submit", "get", "cancel"])
@pytest.mark.parametrize("with_phases", [True, False])
def test_neutral_client_uses_v2_and_refuses_missing_phase_summaries(tmp_path, operation, with_phases):
    body = grant()
    client = UnixLocalActionTransport(tmp_path)
    requests = []

    def exchange(instance_id, request):
        requests.append((instance_id, request))
        return _response(body, phases=[] if with_phases else None)

    client._exchange = exchange
    kwargs = {"reason": "SITE_STOP"} if operation == "cancel" else {}
    if with_phases:
        receipt = getattr(client, operation)(body, **kwargs)
        assert receipt.action_id == body.action_id and receipt.phase_summaries == ()
    else:
        with pytest.raises(LocalActionUnavailable):
            getattr(client, operation)(body, **kwargs)
    assert len(requests) == 1
    assert requests[0][0] == body.instance_id and requests[0][1]["version"] == 2
