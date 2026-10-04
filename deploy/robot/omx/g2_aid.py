"""One-shot acknowledged SIM AID with a 0.2 s wall deadline under the owner fence."""
import time

from cell_sim_tools import SimAid, WORLD

WALL_BUDGET_S = 0.2
# Leave 50 ms for the independent state echo without extending the fenced operation.
REQUEST_TIMEOUT_MS = 150


class OneShotSimAid(SimAid):
    def attach(self, model):
        from gz.msgs10.boolean_pb2 import Boolean
        from gz.msgs10.entity_pb2 import Entity
        from gz.msgs10.entity_plugin_v_pb2 import EntityPlugin_V
        self.watch(model)
        if getattr(self, "_robot_id", None) is None:
            raise RuntimeError("SIM AID robot identity must be read before grants")
        request = EntityPlugin_V()
        request.entity.id, request.entity.name, request.entity.type = self._robot_id, "omx_f", Entity.MODEL
        plugin = request.plugins.add()
        plugin.name, plugin.filename = "gz::sim::systems::DetachableJoint", "gz-sim-detachable-joint-system"
        plugin.innerxml = (
            f"<parent_link>link5</parent_link><child_model>{model}</child_model><child_link>block</child_link>"
            f"<attach_topic>/c3_sim_aid/{model}/attach</attach_topic>"
            f"<detach_topic>/c3_sim_aid/{model}/detach</detach_topic>"
            f"<output_topic>/c3_sim_aid/{model}/state</output_topic>")
        started = time.monotonic()
        ok, response = self._node.request(f"/world/{WORLD}/entity/system/add", request, EntityPlugin_V,
                                          Boolean, REQUEST_TIMEOUT_MS)
        confirmed = self._wait_once(model, "attached", max(0., WALL_BUDGET_S-(time.monotonic()-started)))
        elapsed = time.monotonic()-started
        return {"model": model, "command": "attach_once", "service_ok": bool(ok and response.data),
                "transport_ok": bool(ok), "response_data": bool(response.data),
                "request_timeout_ms": REQUEST_TIMEOUT_MS, "wall_budget_s": WALL_BUDGET_S,
                "confirmed": bool(confirmed and elapsed <= WALL_BUDGET_S), "elapsed_s": elapsed,
                "re_commanded_after": None}

    def _wait_once(self, model, state, limit_s):
        deadline = time.monotonic()+limit_s
        while time.monotonic() < deadline:
            if self._states[model] and self._states[model][-1] == state:
                return True
            time.sleep(max(0., min(0.005, deadline-time.monotonic())))
        return bool(self._states[model]) and self._states[model][-1] == state

    def detach(self, model):
        from gz.msgs10.empty_pb2 import Empty
        self.watch(model)
        started = time.monotonic()
        self._publishers[model].publish(Empty())
        confirmed = self._wait_once(model, "detached", max(0., WALL_BUDGET_S-(time.monotonic()-started)))
        elapsed = time.monotonic()-started
        return {"model": model, "command": "detach_once",
                "confirmed": bool(confirmed and elapsed <= WALL_BUDGET_S),
                "wall_budget_s": WALL_BUDGET_S, "elapsed_s": elapsed, "re_commanded_after": None}
