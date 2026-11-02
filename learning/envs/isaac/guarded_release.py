"""Guarded descent before the gripper opens: lower the held container until its bottom stops (dot tops or plate), then open.

The release feedback loop leaves the TCP a few mm above the seat. Here the TCP goes down in `step_m` steps; the container
has met something when it dropped less than `stall_m` in a step. One step is then lifted again to relieve the preload.
The sensor is the container height (the sim's measured box pose), not a force; the real arm would use jaw height or motor load.
"""


def descend(move, box_z, command, spec):
    """move(point) drives the TCP, box_z() reads the held container height. Returns (final command, log)."""
    command, z, log = list(command), box_z(), []
    for n in range(round(spec['limit_m']/spec['step_m'])):
        command[2] -= spec['step_m']
        move(command)
        drop, z = z-box_z(), box_z()
        log.append(dict(step=n, command_z_m=command[2], box_z_m=z, drop_m=drop))
        if drop < spec['stall_m']:
            command[2] += spec['step_m']
            move(command)
            return command, dict(contact=True, steps=log)
    return command, dict(contact=False, steps=log)
