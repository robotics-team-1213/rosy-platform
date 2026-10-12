"""A model proposal cannot supply a user's positive instruction or its values."""
import re

from core_common.intent import interpret
from rosy.decision.conversation.codec import digest

_PLEASE = r'\s*(?:줘|주세요|줄래|줄래요|주실래요|주십시오|해|하라)(?:요)?[?.!]?'
_NUMBER = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)'


def _aliases(items, names):
    result = {}
    for item in items:
        for name in names(item):
            if name in result and result[name] != item:
                raise ValueError('AMBIGUOUS_REGISTERED_ALIAS')
            result[name] = item
    return result


def positive_plan(question, *, selection=None):
    """Closed imperative grammar; unsupported wording asks for clarification."""
    text = question.question.strip()
    if (not 1 <= len(text) <= 2000 or re.search(r'["\'“”‘’`<>@]|하지|보내지|말고|말아|안\s|않|무시|풀어|비상.*해제|E-?stop.*해제|면|어떻게|설명', text,re.I)):
        raise ValueError('EXPLICIT_POSITIVE_INSTRUCTION_REQUIRED')
    robots = _aliases(question.environment['robots'], lambda r: [r['robot_id']] +
        ([re.search(r'(\d+)$', r['robot_id'])[1]+'번'] if re.search(r'(\d+)$', r['robot_id']) else []))
    map_data = question.environment['map']
    places = _aliases([] if map_data is None else map_data['places'], lambda p:[p['id'], p['name'],p['id']+' 지점'])
    steps = []
    for clause in re.split(r'\s*(?:;|그리고|그다음|다음에)\s*', text):
        clause = re.sub(r'\s+', ' ', clause).strip()
        if re.fullmatch(r'(?:전체|모든 로봇)(?:를|을)? 비상\s*정지(?:해)?'+_PLEASE, clause):
            steps.append({'do':'estop'})
            continue
        if re.fullmatch(r'대형 (중지|정지|재개)(?:해)?'+_PLEASE, clause):
            steps.append({'do':'formation_resume' if '재개' in clause else 'formation_stop'})
            continue
        matching = [(a,r) for a,r in robots.items() if clause.startswith(a)]
        if not matching:
            raise ValueError('EXPLICIT_REGISTERED_TARGET_REQUIRED')
        alias, robot = max(matching, key=lambda row:len(row[0]))
        remaining = clause[len(alias):].strip()
        remaining = re.sub(r'^(?:로봇)?(?:을|를)?\s*', '', remaining).strip()
        rid = robot['robot_id']
        patterns = {'cancel':r'(?:이동 |항법 |작업 )?취소(?:해)?',
                    'stop':r'비상\s*정지(?:해)?', 'home':r'(?:집으로 복귀|홈으로 복귀|귀환)(?:해)?',
                    'follow_cancel':r'추종 (?:취소|중지)(?:해)?', 'undock':r'(?:도킹 해제|언도킹)(?:해)?'}
        verb = next((v for v,p in patterns.items() if re.fullmatch(p+_PLEASE, remaining)), None)
        if verb is not None:
            steps.append({'do':verb, 'robot':rid})
            continue
        target = re.fullmatch(r'(.+?)(?:으로|로) (?:보내|이동시켜|이동해)'+_PLEASE, remaining)
        if target:
            name = target[1].strip()
            if name in {'거기', '그곳'}:
                if selection is None or selection['robot_id'] != rid:
                    raise ValueError('TRUSTED_SELECTION_REQUIRED')
                name = selection['place_id']
            place = places.get(name)
            if place is None or map_data.get('places_complete', True) is not True:
                raise ValueError('REGISTERED_PLACE_REQUIRED')
            steps.append({'do':'navigate','robot':rid, 'waypoint':place['id'],
                          'x':place['x'], 'y':place['y'], 'yaw':place.get('yaw') or 0.0})
            continue
        move = re.fullmatch(r'선속도 ('+_NUMBER+r') m/s 각속도 ('+_NUMBER+r') rad/s로 움직여'+_PLEASE, remaining)
        if move:
            steps.append({'do':'move','robot':rid,'linear':float(move[1]),'angular':float(move[2])})
            continue
        dock = re.fullmatch(r'([A-Za-z0-9_.:-]{1,96})에서 도킹(?:해)?'+_PLEASE, remaining)
        if dock:
            steps.append({'do':'dock','robot':rid,'dock':dock[1]})
            continue
        raise ValueError('SUPPORTED_EXPLICIT_INSTRUCTION_REQUIRED')
    plan = steps[0] if len(steps) == 1 else {'steps':steps}
    interpret(plan)
    return plan


def bind_original(question, proposal, *, selection=None):
    plan = positive_plan(question, selection=selection)
    original = interpret(plan)
    supplied_steps = []
    for call in interpret(proposal):
        body = dict(call.body)
        if call.verb == 'navigate':
            place = next((p for p in question.environment['map']['places']
                          if p['id'] == body.get('waypoint')), None)
            if place is None:
                raise ValueError('REGISTERED_PLACE_REQUIRED')
            for key in ('x', 'y', 'yaw'):
                body.setdefault(key, place.get(key) or 0.0)
        supplied_steps.append({'do':call.verb, **({'robot':call.robot} if call.robot else {}), **body})
    supplied = interpret(supplied_steps[0] if len(supplied_steps) == 1 else {'steps':supplied_steps})
    if supplied != original:
        raise ValueError('MODEL_PROPOSAL_DIFFERS_FROM_ORIGINAL_INSTRUCTION')
    return plan


def catalog_hash(environment):
    return digest({'robot_ids':sorted(r['robot_id'] for r in environment['robots']),
                   'map':environment['map'], 'work_catalog':environment['work_catalog']})
