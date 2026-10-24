import asyncio
import threading

import pytest

from fleet.server import task_dispatch_routes as routes


def test_local_stop_callback_waits_for_omx_thread_after_console_failure(monkeypatch):
    async def exercise():
        started, release, finished = threading.Event(), threading.Event(), threading.Event()

        def omx(*args, **kwargs):
            started.set()
            assert release.wait(5.0)
            finished.set()
            return {"state": "LOCAL_LATCHED", "instances": []}

        class Console:
            async def estop_all(self):
                raise RuntimeError("injected Console failure")

        monkeypatch.setattr(routes, "fanout_local_omx_stops", omx)
        task = asyncio.create_task(routes.execute_local_fleet_stop(
            console=Console(), task_service=None, configured_omx={"cell": "omx"},
            stop_transport=None, stop_control={"authority_epoch": 1, "generation": 2}, actor_id="human"))
        assert await asyncio.to_thread(started.wait, 3.0)
        assert not task.done()
        release.set()
        with pytest.raises(RuntimeError, match="Console failure"):
            await task
        assert finished.is_set()

    asyncio.run(exercise())
