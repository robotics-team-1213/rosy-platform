"""D-148: fleet.bench 공개면은 재수출한 실체와 동일해야 한다.

벤치 파사드가 이름만 갖고 실체를 못 실으면 swarm_bench 는 런타임에야 깨진다.
여기는 import 자체가 계약이다 — fleet 내부가 재조정돼도 이 파일이 초록이면
공개면은 유효하다.
"""

import fleet.bench as bench


def test_facade_reexports_the_real_objects():
    from fleet.formation import geometry
    from fleet.swarm import robots, session, transport

    assert bench.Formation is geometry.Formation
    assert bench.slot_world_position is geometry.slot_world_position
    assert bench.load_robots is robots.load_robots
    assert bench.FormationSession is session.FormationSession
    assert bench.FormationSpec is session.FormationSpec
    assert bench.SessionState is session.SessionState
    assert bench.HttpRobotClient is transport.HttpRobotClient
    assert bench.RobotApiError is transport.RobotApiError


def test_all_matches_the_exported_surface():
    public = {name for name in dir(bench) if not name.startswith("_")}
    assert set(bench.__all__) <= public
    assert len(bench.__all__) == 8
