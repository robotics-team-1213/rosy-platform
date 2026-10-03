"""fleet.bench — 시뮬레이션 벤치가 쓰는 fleet 공개면 (D-148).

gz_sim 의 swarm_bench 는 fleet 내부 모듈(``fleet.swarm.*``,
``fleet.formation.*``)을 직접 import 하지 않고 이 모듈만 본다. fleet 내부를
재조정할 때 이 면의 시그니처만 지키면 벤치는 깨지지 않는다. 벤치가 쓰는
이름이 내부에서 바뀌면 여기서 별칭으로 흡수한다.
"""

from fleet.formation.geometry import Formation, slot_world_position
from fleet.swarm.robots import load_robots
from fleet.swarm.session import FormationSession, FormationSpec, SessionState
from fleet.swarm.transport import HttpRobotClient, RobotApiError

__all__ = [
    "Formation",
    "slot_world_position",
    "load_robots",
    "FormationSession",
    "FormationSpec",
    "SessionState",
    "HttpRobotClient",
    "RobotApiError",
]
