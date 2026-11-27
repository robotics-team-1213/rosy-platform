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
    cell_states = getattr(app.state, 'omx_cell_states', None)
    arm_holds = getattr(app.state, 'arm_holds', None)
    if isinstance(cell_states, dict) and cell_states:
        now_s = time.time()
        tasks = list((getattr(app.state, 'omx_cell_tasks', None) or {}).values())
        for cid in sorted(cell_states):
            cstate = cell_states[cid] or {}
            safe_cid = code(cid, locale)
            arms = ('arm_s',) if cid == 'cell_s' else ('arm_a', 'arm_b')
            held = [a for a in arms if isinstance(arm_holds, dict) and (arm_holds.get(a) or {}).get('held')]
            prop = sum(1 for t in tasks if t.get('cell_id') == cid and t.get('status') == 'PROPOSED')
            run = sum(1 for t in tasks if t.get('cell_id') == cid and t.get('status') == 'RUNNING')
            phase = code(cstate.get('phase'), locale)
            held_txt = ','.join(code(a, locale) for a in held) if held else ('none' if locale == 'en-US' else '없음')
            text = (f'{safe_cid}: phase={phase}, held={len(held)}({held_txt}), proposed={prop}, running={run}'
                    if locale == 'en-US' else f'{safe_cid}: 단계 {phase}, 보류 {len(held)}({held_txt}), 제안 {prop}, 실행 {run}')
            facts.append(AssistantFact(ref=f'cell:{safe_cid}', observed_at=now_s, text=text[:512]))
            if len(facts) > 64:
                raise ValueError('ASSISTANT_CONTEXT_LIMIT')
    if isinstance(arm_holds, dict) and arm_holds:
        now_s = time.time()
        for aid in sorted(arm_holds):
            hold = arm_holds.get(aid) or {}
            if not isinstance(hold, dict) or not hold.get('held'):
                continue
            safe_arm = code(aid, locale)
            why = code(hold.get('reason') or hold.get('code') or 'arm_hold', locale)
            text = (f'{safe_arm}: arm hold active ({why}); inspect open incident and clear with confirmation.'
                    if locale == 'en-US' else f'{safe_arm}: 팔 보류 활성 ({why}); 열린 사건을 확인하고 승인 후 해제할 수 있습니다.')
            facts.append(AssistantFact(ref=f'incident:{safe_arm}', observed_at=now_s, text=text[:512]))
            if len(facts) > 64:
                raise ValueError('ASSISTANT_CONTEXT_LIMIT')
    detected = getattr(app.state, 'cell_detected_objects', None)
    if isinstance(detected, dict) and detected:
        now_s = time.time()
        for cid in sorted(detected):
            safe_cid = code(cid, locale)
            arms_map = (detected.get(cid) or {}).get('by_arm') or {}
            counts: dict[tuple[str, str, bool], int] = {}
            for _aid, snap in sorted(arms_map.items()):
                try:
                    rec = float(snap.get('received_at', 0.0))
                    obs = float(snap.get('observed_at', 0.0))
                    ttl = float(snap.get('ttl_s', 15.0))
                except (TypeError, ValueError):
                    continue
                if (now_s - rec) > ttl or (now_s - obs) > ttl or (now_s - obs) < -5.0:
                    continue
                for obj in snap.get('objects') or ():
                    if not isinstance(obj, dict):
                        continue
                    cat = str(obj.get('catalog_id') or '').strip()
                    if not cat or cat.lower() == 'unmatched':
                        continue
                    site = str(obj.get('site') or '').strip() or ('pinky' if cid == 'cell_s' else 'stand')
                    key = (code(cat, locale), code(site, locale), bool(obj.get('pickable')))
                    counts[key] = counts.get(key, 0) + 1
            if not counts:
                continue
            items = sorted(counts.items())
            shown, extra = items[:8], max(0, len(items) - 8)
            if locale == 'en-US':
                parts = [f'{cat}@{site}(x{n}, {"pickable" if ok else "blocked"})' for (cat, site, ok), n in shown]
                suffix = f' (+ {extra} more)' if extra else ''
                text = f'{safe_cid} catalog objects: ' + ', '.join(parts) + suffix
            else:
                parts = [f'{cat}@{site}({n}개, {"선택가능" if ok else "제한"})' for (cat, site, ok), n in shown]
                suffix = f' (+ 외 {extra}종)' if extra else ''
                text = f'{safe_cid} 카탈로그 객체: ' + ', '.join(parts) + suffix
            facts.append(AssistantFact(ref=f'cell_objects:{safe_cid}', observed_at=now_s, text=text[:512]))
            if len(facts) > 64:
                raise ValueError('ASSISTANT_CONTEXT_LIMIT')
    return facts
