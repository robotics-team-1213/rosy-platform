"""Explicit operator coordinates enter the existing Task owner, never a model tool."""
from hashlib import sha256

from core_common.intent import interpret
from fastapi import HTTPException


class AssistantExecution:
    def __init__(self, service, execution, *, enabled):
        self.service, self.execution, self.enabled = service, execution, enabled

    async def submit(self, principal, request_id, navigation, *, authorized):
        def guard(*_):
            if not self.enabled() or not self.service.admitted():
                raise HTTPException(503, detail='ASSISTANT_EXECUTION_NOT_ADMITTED')
            if not authorized() or not principal.permits_site('fleet.operate', {'operator'}):
                raise HTTPException(403, detail='ASSISTANT_AUTHORITY_CHANGED')
            result, message = self.service.journal.control(principal.principal_id, request_id)
            if not 0 <= self.service.clock()-result.completed_at <= 30:
                raise HTTPException(409, detail='ASSISTANT_CONTROL_EXPIRED')
            if message.selected_robot_id != navigation.robot_id:
                raise HTTPException(409, detail='ASSISTANT_SELECTION_CHANGED')
        guard()
        call, = interpret({'do':'navigate', 'robot':navigation.robot_id,
                          'x':navigation.x, 'y':navigation.y, 'yaw':navigation.yaw})
        key = 'console-assistant:'+sha256((principal.principal_id+'\0'+request_id).encode()).hexdigest()
        return await self.execution.step(call, principal, key, 0, admission=guard)
