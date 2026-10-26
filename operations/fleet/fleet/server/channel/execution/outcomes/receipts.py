"""Documented owner responses prove RPC acknowledgement, never physical success."""
import re
from core_common.protocol.schemas import DockingStatus, NavigationState, SwarmRole, RobotMode
from fleet.swarm.api.types import SessionState
from core_common.protocol.native.operation import NativeOperation
from .evidence import KINDS


def stop_operations(value):
    operations = [NativeOperation.model_validate(op).model_dump(mode='json') for op in value.get('operations', [])]
    owners = [({'home': 'navigate', 'undock': 'dock'}.get(op['kind'], op['kind'])) for op in operations]
    if len(operations) > 4 or len(set(owners)) != len(owners) or len({op['boot_id'] for op in operations}) > 1:
        raise ValueError('NATIVE_STOP_OWNER_SET_INVALID')
    return operations


def owner_receipt(call,value,robot_ids):
    accepted, receipt = _owner_receipt(call,value,robot_ids)
    if value.get('operation') is not None:
        operation = NativeOperation.model_validate(value['operation']).model_dump(mode='json')
        if accepted is False or (call.body.get('expected_boot_id') is not None
                                and operation['boot_id'] != call.body['expected_boot_id']):
            raise ValueError('NATIVE_ACK_ADMISSION_CHANGED')
        if call.verb in KINDS and (operation['kind'] != KINDS[call.verb]
                or operation['correlation_id'] != call.body.get('correlation_id')):
            raise ValueError('NATIVE_ACK_IDENTITY_CHANGED')
        if (call.verb == 'cancel' and operation['kind'] not in {'navigate', 'home'}
                or call.verb == 'follow_cancel' and operation['kind'] != 'follow'):
            raise ValueError('NATIVE_STOP_OWNER_CHANGED')
        receipt['operation'] = operation
    elif call.body.get('correlation_id') and call.verb in KINDS and accepted is True:
        accepted = None
    return accepted, receipt


def _owner_receipt(call,value,robot_ids):
    if type(value) is not dict:raise ValueError('OWNER_RECEIPT_INVALID')
    if call.verb in {'home','move'}:
        if type(value.get('accepted')) is not bool:raise ValueError('OWNER_ACK_REQUIRED')
        receipt={'accepted':value['accepted']}
        if call.verb=='home' and 'mode' in value:receipt['mode']=RobotMode(value['mode']).value
        return value['accepted'],receipt
    if call.verb=='cancel':
        state=NavigationState(value.get('navigation'))
        return True,{'navigation':state.value,'rpc_acknowledged':True}
    if call.verb=='stop':
        if value.get('estop') is not True:raise ValueError('OWNER_STOP_ACK_REQUIRED')
        return True,{'estop':True,'rpc_acknowledged':True,'operations':stop_operations(value)}
    if call.verb in {'dock','undock'}:
        status=DockingStatus.model_validate(value)
        if status.dock_id is not None and (not re.fullmatch(r'[A-Za-z0-9_.:-]{1,96}',status.dock_id)
                or call.verb=='dock' and status.dock_id!=call.body['dock']):raise ValueError('DOCK_RECEIPT_SCOPE_CHANGED')
        if type(value.get('retries')) is not int or not 0<=status.retries<=100:raise ValueError('DOCK_RECEIPT_INVALID')
        return True,{'rpc_acknowledged':True,'state':status.state.value,'dock_id':status.dock_id,
                     'error_present':status.error is not None,'retries':status.retries,
                     'phase':status.phase if status.phase is not None and re.fullmatch(r'[a-z_]{1,32}',status.phase) else None}
    if call.verb in {'follow','follow_cancel'}:
        role=SwarmRole(value.get('role'))
        if type(value.get('active')) is not bool:raise ValueError('SWARM_ACK_REQUIRED')
        target=value.get('target_robot_id')
        if target is not None and target not in robot_ids:raise ValueError('SWARM_TARGET_CHANGED')
        if call.verb=='follow' and target!=call.body['target_robot_id']:raise ValueError('SWARM_TARGET_CHANGED')
        return True,{'rpc_acknowledged':True,'role':role.value,'active':value['active'],'target_robot_id':target}
    if call.verb.startswith('formation_'):
        state=SessionState(value.get('state'))
        if type(value.get('active')) is not bool:raise ValueError('FORMATION_ACK_REQUIRED')
        leader=value.get('leader')
        members=sorted(value.get('assignment',{}))
        if leader is not None and leader not in robot_ids or not set(members)<=set(robot_ids):raise ValueError('FORMATION_SCOPE_CHANGED')
        if call.verb=='formation_start' and (leader!=call.body['leader'] or
                members!=sorted(set(call.body.get('members',robot_ids))-{call.body['leader']})):
            raise ValueError('FORMATION_RECEIPT_NOT_ORIGINAL_SESSION')
        return True,{'rpc_acknowledged':True,'active':value['active'],'state':state.value,'leader':leader,'members':members}
    if call.verb=='estop':
        rows=value.get('robots')
        if type(rows) is not list or len(rows)>len(robot_ids):raise ValueError('SITE_STOP_RECEIPT_REQUIRED')
        result=[]
        for row in rows:
            if row.get('robot_id') not in robot_ids or type(row.get('stopped')) is not bool:raise ValueError('SITE_STOP_RECEIPT_INVALID')
            result.append({'robot_id':row['robot_id'],'rpc_acknowledged':row['stopped'],
                           'estop':(row.get('result') or {}).get('estop') is True})
            operation = (row.get('result') or {}).get('operation')
            if operation is not None:
                result[-1]['operation'] = NativeOperation.model_validate(operation).model_dump(mode='json')
            result[-1]['operations'] = stop_operations(row.get('result') or {})
        if len({r['robot_id'] for r in result})!=len(result):raise ValueError('SITE_STOP_RECEIPT_INVALID')
        complete=set(r['robot_id'] for r in result)==set(robot_ids) and all(r['estop'] and r['rpc_acknowledged'] for r in result)
        return True if complete else None,{'rpc_acknowledged':True,'robots':result}
    raise ValueError('OWNER_RECEIPT_NOT_REGISTERED')
