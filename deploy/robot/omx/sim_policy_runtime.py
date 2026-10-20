"""SIM-only additional step fence over the existing serialized policy admission."""
from rosy.execution.local.policy_runtime import PolicyRuntimeBinding


class SimPolicyRuntimeBinding(PolicyRuntimeBinding):
    def check_command(self, command):
        if not super().check_command(command):
            return False
        try:
            if self.session._authority(self.session.lease) is not True:
                return False
        except Exception:
            return False
        current = self.owner._joint_state
        return current is not None and all(
            abs(value-current.positions[name]) <= .04
            for point in command.trajectory_points
            for name, value in zip(command.joint_names, point.positions))


def bind_sim_runtime(session, runtime):
    with session._lock:
        if session._runtime_binding is not None:
            raise ValueError('runtime already bound')
        session._runtime_binding = SimPolicyRuntimeBinding(session, runtime)
