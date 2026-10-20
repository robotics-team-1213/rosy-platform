"""Server-authored replies keep physical claims tied to displayed observations."""
TEXT = {
    'ko-KR': {
        'STATUS':'관제에서 확인한 상태입니다.', 'NO_STATUS':'조회할 관제 상태가 없습니다.',
        'CAUSE':'기록된 사건 근거입니다.', 'NO_CAUSE':'기록된 정지 원인을 확인하지 못했습니다. 사건 기록을 확인해 주세요.',
        'CHAT':'안녕하세요. 로봇 상태 조회와 사건 근거 확인을 도와드릴 수 있습니다. 확인할 로봇과 내용을 알려주세요.',
        'CONTROL':'이 대화의 답변은 실행을 승인하지 않습니다. 작업 화면에서 로봇과 목적지를 지정해 주세요.',
        'CLARIFY':'대상을 확정할 수 없습니다. 로봇 이름과 확인할 내용을 구체적으로 알려주세요.',
        'REFUSE':'권한이나 안전 규칙을 우회하는 요청은 처리할 수 없습니다.'},
    'en-US': {
        'STATUS':'Current observations from Fleet.', 'NO_STATUS':'No current observations are available.',
        'CAUSE':'Recorded incident evidence.', 'NO_CAUSE':'The stop cause is unknown. Check the incident record.',
        'CHAT':'Hello. I can check robot status and incident evidence. Specify the robot and your question.',
        'CONTROL':'This answer does not authorize execution. Select a robot and destination in the work view.',
        'CLARIFY':'The target is unclear. Specify the robot and what you want to check.',
        'REFUSE':'Requests to bypass permissions or safety rules cannot be processed.'},
}


def reply(kind, facts, locale):
    words = TEXT[locale]
    if kind == 'CAUSE': facts = [f for f in facts if f.ref.startswith('incident:')]
    if kind in {'STATUS', 'CAUSE'}:
        return (words[kind]+'\n'+'\n'.join(f.text for f in facts) if facts else words['NO_'+kind]), facts
    return words[kind], []
