"""Sample dialogue receipts with explicit completion and idempotency."""
import re

from response import error, reply


class Assistant:
    def __init__(self):
        self.messages, self.inputs = {}, {}

    def advance(self, event):
        states = {'answer': 'ANSWERED', 'hold': 'HOLD', 'unknown': 'UNKNOWN'}
        pending = [row for row in self.messages.values() if row['state'] in ('PENDING', 'RUNNING')]
        if event not in states or not pending:
            raise ValueError('unknown event or no pending message')
        for row in pending:
            row.update(state=states[event], completed_at=row['created_at'] + 1,
                       response='샘플 로봇 1대의 상태를 확인했습니다. 실제 장치 명령은 보내지 않았습니다.' if event == 'answer' else None,
                       reason=None if event == 'answer' else 'SAMPLE_' + event.upper())

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
                'completed_at': None, 'action_admissible': False}
            return reply(self.messages[identifier], 202)
        match = re.fullmatch(r'/assistant/messages/([A-Za-z0-9_-]{1,96})', path)
        if method == 'GET' and match:
            row = self.messages.get(match[1])
            return reply(row) if row else error(404, 'ASSISTANT_MESSAGE_NOT_FOUND')
        return None
