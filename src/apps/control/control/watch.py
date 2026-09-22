"""Subject: node interruptions. Pure graph check — no ROS.

Local stack must be one of each required node. Exclusive topics
must be owned by the local node, not a remote gazebo/bridge twin.
"""
from collections import Counter
from dataclasses import dataclass, field


REQUIRED = (
    'sllidar_node',
    'bringup',
    'sensor_adc',
    'led_service_server',
    'imu_bno055',
    'camera_detect_node',
    'safety_node',
    'wander_node',
)

OPTIONAL = ('lcd_node', 'web_node')

# topic -> local nodes that may own it. Exactly one distinct owner must be
# publishing at a time (D-2/D-38: CORE owns the final cmd_vel in the OS
# runtime; the legacy safety gate owns it only in control-standalone mode,
# D-149 — the two publishing together is an interrupt, not a mode choice).
EXCLUSIVE = {
    '/cmd_vel': frozenset({'core', 'safety_node'}),
    '/cmd_vel_raw': frozenset({'wander_node'}),
    '/scan': frozenset({'sllidar_node'}),
}

# Local extras that are not a fight (safety zeros /cmd_vel_raw on e-stop,
# the odom-P controller and teleop surfaces also write candidates).
ALLOWED = {
    '/cmd_vel_raw': frozenset({'safety_node', 'web_node',
                               'startup_calibration_node', 'calib_node',
                               'control_node'}),
}

FOREIGN = frozenset({
    'parameter_bridge',
    'image_bridge',
})

IGNORE_NODES = frozenset({
    'watch_node',
    'graph_probe',
    'transform_listener_impl',
})


@dataclass(frozen=True)
class Issue:
    kind: str
    topic: str
    node: str
    detail: str


@dataclass
class Report:
    ok: bool
    issues: list = field(default_factory=list)
    nodes: dict = field(default_factory=dict)

    def line(self) -> str:
        if self.ok:
            return 'ok'
        return '; '.join(i.detail for i in self.issues)


def _bare(name: str) -> str:
    n = (name or '').strip()
    if n.startswith('/'):
        n = n[1:]
    if '/' in n:
        n = n.rsplit('/', 1)[-1]
    return n


def inspect(node_names, pubs_by_topic, *, namespace=None) -> Report:
    """node_names: iterable of node name strings.
    pubs_by_topic: {logical topic: [publisher node names]}.
    With namespace set, names must be fully qualified. Nodes from another
    robot are irrelevant, but their publishers on our topics are violations.
    """
    scope = '/' + namespace.strip('/') if namespace is not None else None

    def local(name):
        if scope is None:
            return True
        return name.startswith('/') and (name.rsplit('/', 1)[0] or '/') == scope

    counts = Counter(_bare(n) for n in node_names if local(n) and _bare(n) not in IGNORE_NODES)
    issues = []
    for name in REQUIRED:
        n = counts.get(name, 0)
        if n == 0:
            issues.append(Issue('missing', '', name, f'missing {name}'))
        elif n > 1:
            issues.append(Issue('duplicate', '', name, f'duplicate {name} x{n}'))
    for name in OPTIONAL:
        n = counts.get(name, 0)
        if n > 1:
            issues.append(Issue('duplicate', '', name, f'duplicate {name} x{n}'))
    for topic, allowed in EXCLUSIVE.items():
        endpoints = pubs_by_topic.get(topic) or []
        outside = [p for p in endpoints if not local(p)]
        if outside:
            who = ','.join(sorted(set(outside)))
            issues.append(Issue('foreign_namespace', topic, who, f'{topic} outside namespace: {who}'))
        pubs = [_bare(p) for p in endpoints if local(p)]
        owners = [p for p in pubs if p in allowed]
        foreign = [p for p in pubs if p in FOREIGN]
        allow = ALLOWED.get(topic, frozenset())
        extra = [
            p for p in pubs
            if p not in FOREIGN and p not in allowed and p not in IGNORE_NODES and p not in allow
        ]
        if not owners:
            label = '/'.join(sorted(allowed))
            issues.append(Issue('missing_pub', topic, label, f'{topic} has no {label}'))
        distinct = sorted(set(owners))
        if len(distinct) > 1:
            who = ','.join(distinct)
            issues.append(Issue('co_owner', topic, who, f'{topic} owners conflict: {who}'))
        for name in distinct:
            if owners.count(name) > 1:
                issues.append(Issue('duplicate', topic, name, f'{topic} {name} x{owners.count(name)}'))
        if foreign:
            who = ','.join(sorted(set(foreign)))
            issues.append(Issue('foreign', topic, who, f'{topic} interrupted by {who}'))
        if extra:
            who = ','.join(sorted(set(extra)))
            issues.append(Issue('extra', topic, who, f'{topic} extra {who}'))
    return Report(ok=not issues, issues=issues, nodes=dict(counts))
