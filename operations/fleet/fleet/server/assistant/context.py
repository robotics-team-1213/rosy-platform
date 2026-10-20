"""Bounded operator facts from the existing Fleet observation owner."""
import re
import time

from core_common.protocol.assistant import AssistantFact
from ..channel.model_runtime import fresh_snapshot


def code(value, locale='ko-KR'):
    return value if type(value) is str and re.fullmatch(r'[A-Za-z0-9_.:-]{1,96}', value) else 'unknown' if locale == 'en-US' else '미확인'


async def build_context(app, principal, selected_robot_id, locale='ko-KR'):
    gather = app.state.fleet_gather
    await gather()
    snapshot = fresh_snapshot(gather._snapshot, gather.gathered_at, gather._console._clock())
    rows = snapshot['robots']
    if selected_robot_id and selected_robot_id not in {r['robot_id'] for r in rows}:
        raise ValueError('ASSISTANT_SELECTION_CHANGED')
    facts = []
    for row in sorted(rows, key=lambda r:r['robot_id']):
        robot = row['robot_id']
        if selected_robot_id and robot != selected_robot_id:
            continue
        state = row.get('state') if row.get('online') is True else None
        state = state if type(state) is dict else {}
        online = '온라인' if row.get('online') is True else '오프라인' if row.get('online') is False else '통신 상태 미확인'
        safety = state.get('safety') or {}
        estop = '잠김' if safety.get('estop') is True else '해제' if safety.get('estop') is False else '미확인'
        line = state.get('line_follow') or {}
        text = f'{robot}: {online}, 모드 {code(state.get("mode"))}, 비상정지 {estop}, 주행 {code(line.get("state"))}'
        if locale == 'en-US':
            text = f'{robot}: online={row.get("online")}, mode={code(state.get("mode"), locale)}, estop={safety.get("estop")}, line={code(line.get("state"), locale)}'
        facts.append(AssistantFact(ref='robot:'+robot, observed_at=snapshot['observed_at'],
            text=text))
        stuck = app.state.line_stuck.view(robot) if state else None
        if stuck is not None and stuck.get('observed_age_s', 999) <= 5:
            text = (f'{robot}: open stuck incident {code(stuck.get("stuck_id"), locale)}; check the incident record for the cause.'
                if locale == 'en-US' else f'{robot}: 열린 주행 막힘 사건 {code(stuck.get("stuck_id"))}; 원인 판정은 사건 기록에서 확인해야 합니다.')
            facts.append(AssistantFact(ref='incident:'+robot, observed_at=time.time(), text=text))
        if len(facts) > 64:
            raise ValueError('ASSISTANT_CONTEXT_LIMIT')
    return facts
