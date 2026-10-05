"""Bounded display evidence; dispatch always checks CORE capabilities separately."""
import asyncio
import copy


class CapabilityDisplay:
    def __init__(self, clients, clock):
        self.clients, self.clock = clients, clock
        self.cache = {}
        self.pending = {}

    def invalidate(self, robot_id):
        self.cache.pop(robot_id, None)
        task = self.pending.pop(robot_id, None)
        if task is not None:
            task.cancel()

    async def shown(self, robot_id):
        cached = self.cache.get(robot_id)
        if cached is not None and self.clock() - cached[0] < 5.0:
            return copy.deepcopy(cached[1])
        client = self.clients.get(robot_id)
        if client is None:
            return None
        task = self.pending.get(robot_id)
        if task is None:
            task = asyncio.create_task(self._refresh(robot_id, client))
            self.pending[robot_id] = task
        await asyncio.wait({task}, timeout=0.05)
        cached = self.cache.get(robot_id)
        if self.clients.get(robot_id) is not client or cached is None:
            return None
        return copy.deepcopy(cached[1]) if self.clock() - cached[0] < 5.0 else None

    async def _refresh(self, robot_id, client):
        try:
            try:
                caps = await client.capabilities()
            except Exception:
                caps = None
            if self.clients.get(robot_id) is client:
                shown = copy.deepcopy(caps) if isinstance(caps, dict) else None
                self.cache[robot_id] = (self.clock(), shown)
        finally:
            if self.pending.get(robot_id) is asyncio.current_task():
                self.pending.pop(robot_id)

    async def aclose(self):
        tasks = list(self.pending.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
