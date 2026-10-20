"""HOST cache fault semantics; actual Fleet HTTP is verified separately in native SIM."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'deploy/robot/omx'))
from sim_policy_fleet import SimFleetFence


class Client:
    def __init__(self):
        self.value=dict(dispatch_enabled=True,authority_epoch=1,generation=2)
    def request(self,method,path):
        assert (method,path)==('GET','/api/fleet/dispatch-control')
        if isinstance(self.value,Exception):raise self.value
        return self.value


def test_only_fresh_actual_tuple_is_current_and_staleness_latches():
    clock=[10.];client=Client()
    fence=SimFleetFence(client,authority_epoch=1,generation=2,monotonic=lambda:clock[0])
    assert not fence.current(1,2)
    assert fence.refresh()
    assert fence.current(1,2) and not fence.current(1,3)
    clock[0]+=.201
    assert not fence.current(1,2)
    assert not fence.refresh() and not fence.current(1,2)


def test_closed_or_replaced_generation_cannot_recover_automatically():
    for change in [dict(dispatch_enabled=False),dict(generation=3),dict(authority_epoch=2)]:
        client=Client();fence=SimFleetFence(client,authority_epoch=1,generation=2,monotonic=lambda:10.)
        assert fence.refresh()
        client.value.update(change)
        assert not fence.refresh() and not fence.current(1,2)
        client.value=dict(dispatch_enabled=True,authority_epoch=1,generation=2)
        assert not fence.refresh()


def test_failed_request_is_unknown_and_latched():
    client=Client();fence=SimFleetFence(client,authority_epoch=1,generation=2,monotonic=lambda:10.)
    assert fence.refresh()
    client.value=TimeoutError('HTTP timeout')
    assert not fence.refresh() and not fence.current(1,2)
    assert fence.error=='TimeoutError'
