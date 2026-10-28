"""A slow G2 workflow must not exclude the default-group simulation clock callback."""
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1] / "deploy/robot/omx"))


def test_sim_clock_can_advance_while_workflow_callback_is_blocked(monkeypatch):
    from g2_owner import create_workflow_timer

    class ExclusiveGroup:
        def __init__(self):
            self.lock = threading.Lock()

        def invoke(self, callback):
            with self.lock:
                callback()

    # Mirrors installed rclpy's documented mutual exclusion, without starting DDS.
    monkeypatch.setitem(sys.modules, "rclpy.callback_groups",
                        SimpleNamespace(MutuallyExclusiveCallbackGroup=ExclusiveGroup))
    default = ExclusiveGroup()

    class Node:
        def create_timer(self, _period, callback, *, callback_group=None):
            group = callback_group if callback_group is not None else default
            return lambda: group.invoke(callback)

    entered, release, advanced = threading.Event(), threading.Event(), threading.Event()

    def slow_workflow():
        entered.set()
        release.wait(5)

    workflow = threading.Thread(target=create_workflow_timer(Node(), slow_workflow), daemon=True)
    clock = threading.Thread(target=lambda: default.invoke(advanced.set), daemon=True)
    workflow.start()
    try:
        assert entered.wait(2), "workflow did not begin"
        clock.start()
        assert advanced.wait(2), "workflow excluded the default-group /clock callback"
        assert workflow.is_alive(), "clock progress must precede workflow completion"
    finally:
        release.set()
        workflow.join(2)
        if clock.ident is not None:
            clock.join(2)
