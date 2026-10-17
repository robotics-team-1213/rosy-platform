"""Retire an exact completed-work Console projection after the existing native handover."""
from copy import deepcopy


class CompletedWorkHandover:
    def __init__(self, tasks, console):
        self.tasks, self.console = tasks, console

    def _quiet(self, robot):
        c = self.console
        members = c._formation_members()
        return (all(robot not in table for table in (c._goal_busy, c.goal_leases.pending,
                    c._queued, c._yielding, c._held))
                and robot not in members and c._formation_leader != robot)

    async def complete(self, robot_id, *, client, admission, expected_boot_id=None):
        c = self.console
        if c.clients().get(robot_id) is not client or not self._quiet(robot_id):
            return False
        manager = c.goal_leases
        token = manager.handover_token(robot_id)
        goal, claim, lease = c._goals.get(robot_id), c._claims.get(robot_id), manager.get(robot_id)
        copies = deepcopy((goal, claim, lease))

        def retire(*, task, operation):
            if (c.clients().get(robot_id) is not client or c.goal_leases is not manager
                    or not self._quiet(robot_id) or manager.handover_token(robot_id) != token
                    or c._goals.get(robot_id) is not goal or c._claims.get(robot_id) is not claim
                    or manager.get(robot_id) is not lease or (goal, claim, lease) != copies
                    or task['robot_id'] != robot_id or task['attempt_id'] != operation['correlation_id']):
                return False
            if lease is not None:
                if lease.get('state') == 'leased':
                    if (lease.get('source'), lease.get('task_id'), lease.get('correlation_id')) != (
                            'dispatch', task['task_id'], task['attempt_id']):
                        return False
                elif lease != {'state': 'unbounded'}:
                    return False
                # An unbounded entry is display-only; exact Task/CORE proof is still required.
            # No await after the final checks. No device-state or durable-claim writes.
            c._goals.pop(robot_id, None)
            c._claims.pop(robot_id, None)
            c.trip_goal_sent_at.pop(robot_id, None)
            manager.pop(robot_id, None)
            return True

        return await self.tasks.handover_completed_navigation(robot_id, client=client, admission=admission,
            expected_boot_id=expected_boot_id, completed=retire)
