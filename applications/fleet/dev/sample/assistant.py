"""Sample dialogue receipts with explicit completion and idempotency."""
import math
import re

from response import error, reply


class Assistant:
    def __init__(self):
        self.messages, self.inputs, self.navigations = {}, {}, {}

    def advance(self, event):
        states = {'answer': 'ANSWERED', 'control': 'ANSWERED', 'hold': 'HOLD', 'unknown': 'UNKNOWN'}
        pending = [row for row in self.messages.values() if row['state'] in ('PENDING', 'RUNNING')]
        if event not in states or not pending:
            raise ValueError('unknown event or no pending message')
        for row in pending:
            kind = 'STATUS' if event == 'answer' else ('CONTROL' if event == 'control' else None)
            text = ('이 대화의 답변은 실행을 승인하지 않습니다. 아래 입력이나 작업 화면에서 확인 후 접수해 주세요.' if event == 'control'
                    else '샘플 로봇 1대의 상태를 확인했습니다. 실제 장치 명령은 보내지 않았습니다.' if event == 'answer' else None)
            row.update(state=states[event], completed_at=row['created_at'] + 1, kind=kind,
                       response=text, reason=None if states[event] == 'ANSWERED' else 'SAMPLE_' + event.upper())

    def handle(self, method, path, body):
        if (method, path) == ('GET', '/assistant/status'):
            return reply({'available': True, 'mode': 'READ_ONLY', 'reason': None, 'execution_enabled': False})
        if (method, path) == ('POST', '/assistant/messages'):
            if (not isinstance(body.get('text'), str) or not 1 <= len(body['text'].strip()) <= 2000
                    or not all(isinstance(body.get(key), str) and re.fullmatch(r'[A-Za-z0-9_-]{1,96}', body[key])
                               for key in ('request_id', 'conversation_id'))
                    or body.get('locale', 'ko-KR') not in ('ko-KR', 'en-US')):
                return error(422, 'ASSISTANT_MESSAGE_INVALID')
            identifier = body['request_id']
            if identifier in self.messages:
                if body != self.inputs[identifier]:
                    return error(409, 'IDEMPOTENCY_CONFLICT')
                return reply(self.messages[identifier])
            self.inputs[identifier] = body.copy()
            self.messages[identifier] = {
                'request_id': identifier, 'conversation_id': body['conversation_id'], 'text': body['text'],
                'state': 'PENDING', 'response': None, 'reason': None, 'facts': [], 'created_at': 1792454400,
                'completed_at': None, 'kind': None, 'action_admissible': False}
            return reply(self.messages[identifier], 202)
        nav_match = re.fullmatch(r'/assistant/messages/([A-Za-z0-9_-]{1,96})/navigation', path)
        if method == 'POST' and nav_match:
            identifier = nav_match[1]
            row = self.messages.get(identifier)
            if not row:
                return error(404, 'ASSISTANT_NOT_FOUND')
            if row['state'] != 'ANSWERED' or row.get('kind') != 'CONTROL':
                return error(409, 'ASSISTANT_CONTROL_REQUIRED')
            robot_id = body.get('robot_id')
            x, y, yaw = body.get('x'), body.get('y'), body.get('yaw', 0.0)
            if (not isinstance(robot_id, str) or not robot_id
                    or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (x, y, yaw))):
                return error(400, 'ASSISTANT_NAVIGATION_INVALID')
            coords = (robot_id, float(x), float(y), float(yaw))
            if identifier in self.navigations:
                if self.navigations[identifier][0] != coords:
                    return error(409, 'ASSISTANT_NAVIGATION_CHANGED')
                return reply(self.navigations[identifier][1])
            receipt = {'accepted': True, 'queued': True, 'task': {
                'task_id': f'sample-nav-{len(self.navigations) + 1}', 'robot_id': robot_id, 'status': 'QUEUED'}}
            self.navigations[identifier] = (coords, receipt)
            return reply(receipt)
        match = re.fullmatch(r'/assistant/messages/([A-Za-z0-9_-]{1,96})', path)
        if method == 'GET' and match:
            row = self.messages.get(match[1])
            return reply(row) if row else error(404, 'ASSISTANT_MESSAGE_NOT_FOUND')
        return None
