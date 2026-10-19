"""Observe real app workers while the SIM sensor clock remains fixed."""
import asyncio
import traceback


class PipelineClock:
    def __init__(self):
        self.started = asyncio.Event()
        self.changed = asyncio.Condition()
        self.generations = {}
        self.tasks = {}

    def observe(self, owner, name):
        original = getattr(owner, name)
        key = f'{type(owner).__name__}.{name}'
        self.generations[key] = 0
        self.tasks[key] = set()

        async def observed(*args, **kwargs):
            self.tasks[key].add(asyncio.current_task())
            await self.started.wait()
            result = await original(*args, **kwargs)
            async with self.changed:
                self.generations[key] += 1
                self.changed.notify_all()
            return result

        setattr(owner, name, observed)

    def trace_calls(self, motion, failures):
        original = motion.call

        async def traced(function, *args, **kwargs):
            try:
                return await original(function, *args, **kwargs)
            except Exception:
                failures.append(function.__qualname__ + '\n' + traceback.format_exc())
                raise

        motion.call = traced

    async def wait(self):
        async with self.changed:
            previous = self.generations.copy()
            await asyncio.wait_for(self.changed.wait_for(
                lambda: all(value > previous[key] for key, value in self.generations.items())), 3.)

    def assert_stopped(self):
        for tasks in self.tasks.values():
            assert len(tasks) == 1 and all(task.done() for task in tasks)
