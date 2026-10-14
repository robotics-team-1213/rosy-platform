"""Native Task navigation binds a CORE run, rather than caller CID alone."""

from uuid import uuid4
import asyncio
from types import SimpleNamespace
from functools import partial
import pytest

from fakes import run
from fleet.server.task_service import FleetTaskService
from fleet.server.task_store import FleetTaskStore


def test_slow_native_owner_does_not_block_another_tasks_completion(tmp_path):
    from fleet.server.channel.execution.outcomes.reconcile import reconcile_tasks
    from test_channel_native_outcomes import _readback

    service, first, _, _ = _accepted_native_task(tmp_path, robot_ids={"rosy_01", "rosy_02"})
    run(service.submit_navigation(robot_id="rosy_02", x=1., y=2., source="operator",
                                  actor_id="op", request_key="second-native-goal"))

    async def dispatch(attempt):
        return {"accepted": True, "operation": first["receipt"]["operation"] | {
            "run_id": str(uuid4()), "correlation_id": attempt["attempt_id"]}}

    second = run(service.dispatch_next({"rosy_02"}, dispatch=dispatch))
    slow, fast = sorted((first, second), key=lambda task: task["task_id"])

    async def exercise():
        fast_read = asyncio.Event()

        async def slow_get(path):
            await fast_read.wait()
            return _readback(slow["receipt"]["operation"])

        async def fast_get(path):
            fast_read.set()
            return _readback(fast["receipt"]["operation"])

        clients = {slow["robot_id"]: SimpleNamespace(_get=slow_get),
                   fast["robot_id"]: SimpleNamespace(_get=fast_get)}
        await reconcile_tasks(service, SimpleNamespace(_client=clients.__getitem__))
        for task in (slow, fast):
            result = service.store.get_task(task["task_id"])
            assert result["status"] == "COMPLETED"
            assert result["receipt"]["safe_released"] is True
            assert not service.store.resource_claims(resource_kind="robot", resource_id=task["robot_id"])

    run(exercise())


def _accepted_native_task(tmp_path, *, robot_ids={"rosy_01"}):
    store = FleetTaskStore(tmp_path / "fleet.sqlite3")
    service = FleetTaskService(store, robot_ids=robot_ids)
    control = store.dispatch_control()
    store.rearm_dispatch(expected_generation=control["generation"], actor_id="operator")
    queued = run(service.submit_navigation(
        robot_id="rosy_01", x=1.0, y=2.0, source="operator",
        actor_id="site-console", request_key="one-native-goal"))
    run_id, boot_id = uuid4(), uuid4()

    async def dispatch(attempt):
        return {"accepted": True, "operation": {
            "run_id": str(run_id), "boot_id": str(boot_id), "kind": "navigate",
            "correlation_id": attempt["attempt_id"], "phase": "SUBMITTED",
            "result": None, "reason": None,
        }}

    accepted = run(service.dispatch_next({"rosy_01"}, dispatch=dispatch))
    assert accepted["task_id"] == queued["task_id"]
    assert accepted["status"] == "ACCEPTED"
    return service, accepted, run_id, boot_id


def test_task_keeps_first_core_native_receipt_with_its_attempt(tmp_path):
    _, accepted, run_id, boot_id = _accepted_native_task(tmp_path)
    assert accepted["receipt"]["operation"]["run_id"] == str(run_id)
    assert accepted["receipt"]["operation"]["boot_id"] == str(boot_id)
    assert accepted["receipt"]["operation"]["correlation_id"] == accepted["attempt_id"]


def test_same_caller_cid_cannot_complete_another_native_run(tmp_path):
    service, accepted, run_id, boot_id = _accepted_native_task(tmp_path)
    wrong = service.project_core_event({
        "robot_id": "rosy_01", "event_id": "wrong-run", "seq": 1,
        "type": "nav.completed", "data": {
            "correlation_id": accepted["attempt_id"],
            "run_id": str(uuid4()), "boot_id": str(boot_id),
        },
    })
    assert wrong is not None
    assert service.store.get_task(accepted["task_id"])["status"] == "ACCEPTED"

    right = service.project_core_event({
        "robot_id": "rosy_01", "event_id": "right-run", "seq": 2,
        "type": "nav.completed", "data": {
            "correlation_id": accepted["attempt_id"],
            "run_id": str(run_id), "boot_id": str(boot_id),
        },
    })
    assert right is not None and right["status"] == "COMPLETED"
    assert service.store.resource_claims(resource_kind='robot',resource_id='rosy_01')


def test_exact_audited_event_before_first_receipt_is_backfilled(tmp_path):
    from fleet.observe.events import CoreEventStore
    store=FleetTaskStore(tmp_path/'fleet.sqlite3');service=FleetTaskService(store,robot_ids={'rosy_01'})
    service.core_events=CoreEventStore(store.path)
    store.rearm_dispatch(expected_generation=store.dispatch_control()['generation'],actor_id='operator')
    queued=run(service.submit_navigation(robot_id='rosy_01',x=1.,y=2.,source='operator',actor_id='op',request_key='early'))
    async def dispatch(attempt):
        operation={'boot_id':str(uuid4()),'run_id':str(uuid4()),'kind':'navigate',
            'correlation_id':attempt['attempt_id'],'phase':'SUBMITTED','result':None,'reason':None}
        event={'robot_id':'rosy_01','event_id':'before-ack','seq':1,'type':'nav.completed',
            'data':{k:operation[k] for k in ('boot_id','run_id','correlation_id')}}
        service.core_events.append_event(event);service.project_core_event(event)
        assert store.get_task(queued['task_id'])['status']=='QUEUED'
        receipt={'accepted':True,'operation':operation}
        service.bind_native_receipt(attempt['task_id'],attempt['attempt_id'],'rosy_01',receipt)
        assert store.get_task(queued['task_id'])['status']=='COMPLETED'
        return receipt
    result=run(service.dispatch_next({'rosy_01'},dispatch=dispatch))
    assert result['status']=='COMPLETED' and result['receipt']['operation']['run_id']
    assert store.resource_claims(resource_kind='robot',resource_id='rosy_01')


def test_goal_lease_binds_before_late_stop_cancel_await(tmp_path):
    from fleet.server.goal_lease import GoalLeases, NavigationStopped
    store=FleetTaskStore(tmp_path/'fleet.sqlite3');service=FleetTaskService(store,robot_ids={'rosy_01'})
    store.rearm_dispatch(expected_generation=store.dispatch_control()['generation'],actor_id='operator')
    run(service.submit_navigation(robot_id='rosy_01',x=1.,y=2.,source='operator',actor_id='op',request_key='late-stop'))
    task=service.scheduler.claim_next({'rosy_01'});attempt=service.scheduler.begin_dispatch(task['task_id'])
    leases=GoalLeases(0,{});leases.bind_native_receipt=service.bind_native_receipt
    operation={'run_id':str(uuid4()),'boot_id':str(uuid4()),'kind':'navigate',
        'correlation_id':attempt['attempt_id'],'phase':'SUBMITTED','result':None,'reason':None}
    async def goal(*args,**kwargs):
        leases.clear()
        return {'accepted':True,'operation':operation}
    async def cancel():
        assert store.get_task(task['task_id'])['receipt']['operation']==operation
        return {'navigation':'CANCELED'}
    with pytest.raises(NavigationStopped):
        run(leases.send('rosy_01',SimpleNamespace(navigation_goal=goal,navigation_cancel=cancel),{},
                        1.,2.,0.,attempt['attempt_id'],task_id=task['task_id']))


def test_lost_native_ack_never_accepts_legacy_event(tmp_path):
    service,accepted,_,_=_accepted_native_task(tmp_path)
    with service.store._connect() as conn,conn:
        conn.execute('UPDATE fleet_tasks SET receipt_json=?', ('{"native_required":true}',))
    service.project_core_event({'robot_id':'rosy_01','event_id':'legacy','seq':1,'type':'nav.completed',
        'data':{'correlation_id':accepted['attempt_id']}})
    assert service.store.get_task(accepted['task_id'])['status']=='ACCEPTED'
    assert service.store.resource_claims(resource_kind='robot',resource_id='rosy_01')


def test_explicit_non_native_task_keeps_legacy_projection(tmp_path):
    service,accepted,_,_=_accepted_native_task(tmp_path)
    with service.store._connect() as conn,conn:
        conn.execute('UPDATE fleet_tasks SET receipt_json=?', ('{"accepted":true}',))
    task=service.project_core_event({'robot_id':'rosy_01','event_id':'legacy','seq':1,'type':'nav.completed',
        'data':{'correlation_id':accepted['attempt_id']}})
    assert task['status']=='COMPLETED'
    assert not service.store.resource_claims(resource_kind='robot',resource_id='rosy_01')


def test_task_readback_releases_only_after_fresh_native_quiescence(tmp_path):
    from fleet.server.channel.execution.outcomes.reconcile import task_result
    from test_channel_native_outcomes import _readback
    service,accepted,_,_=_accepted_native_task(tmp_path)
    value=_readback(accepted['receipt']['operation'],quiescent=False)
    async def get(path):return value
    client=SimpleNamespace(_get=get)
    run(task_result(service.store,client,accepted))
    current=service.store.get_task(accepted['task_id'])
    assert current['receipt']['outcome']['result']=='SUCCEEDED'
    assert service.store.resource_claims(resource_kind='robot',resource_id='rosy_01')
    value['quiescence']['quiescent']=True
    run(task_result(service.store,client,current))
    result=service.store.get_task(accepted['task_id'])
    assert result['status']=='COMPLETED' and result['receipt']['safe_released'] is True
    assert not service.store.resource_claims(resource_kind='robot',resource_id='rosy_01')


def test_native_terminal_event_cannot_be_replaced_by_conflicting_readback(tmp_path):
    from fleet.server.channel.execution.outcomes.reconcile import task_result
    from test_channel_native_outcomes import _readback
    service,accepted,run_id,boot_id=_accepted_native_task(tmp_path)
    service.project_core_event({'robot_id':'rosy_01','event_id':'done','seq':1,'type':'nav.completed',
        'data':{'correlation_id':accepted['attempt_id'],'run_id':str(run_id),'boot_id':str(boot_id)}})
    current=service.store.get_task(accepted['task_id'])
    async def get(path):return _readback(accepted['receipt']['operation'],result='FAILED')
    run(task_result(service.store,SimpleNamespace(_get=get),current))
    assert service.store.get_task(accepted['task_id'])['receipt']['outcome']['result']=='SUCCEEDED'
    assert service.store.resource_claims(resource_kind='robot',resource_id='rosy_01')


def test_rejection_cleanup_never_erases_bound_native_operation(tmp_path):
    service, accepted, _, _ = _accepted_native_task(tmp_path)
    for receipt, unsent in [({'accepted': False}, False), (None, True)]:
        service.bind_native_receipt(accepted['task_id'], accepted['attempt_id'], 'rosy_01', receipt, unsent=unsent)
        assert service.store.get_task(accepted['task_id'])['receipt'] == accepted['receipt']
        assert service.store.resource_claims(resource_kind='robot', resource_id='rosy_01')


def test_native_task_canceled_event_preserves_expiry_without_release(tmp_path):
    service, accepted, run_id, boot_id = _accepted_native_task(tmp_path)
    task = service.project_core_event({'robot_id': 'rosy_01', 'event_id': 'expired', 'seq': 1,
        'type': 'nav.canceled', 'data': {'source': 'goal_lease', 'correlation_id': accepted['attempt_id'],
                                       'run_id': str(run_id), 'boot_id': str(boot_id)}})
    assert task['status'] == 'UNKNOWN'
    assert task['receipt']['outcome']['result'] == 'EXPIRED'
    assert task['receipt']['outcome']['reason'] == 'LEASE_EXPIRED'
    assert not task['receipt'].get('safe_released')
    assert service.store.resource_claims(resource_kind='robot', resource_id='rosy_01')


def test_stop_during_new_epoch_read_refuses_goal_before_send():
    from fleet.server.goal_lease import GoalLeases, NavigationStopped
    from fleet.server.channel.execution.outcomes.task_receipt import prepare_send
    leases=GoalLeases(0,{})
    leases.prepare_send=partial(prepare_send, leases)
    leases.native_required=lambda tid:True
    sent=[]
    async def get(path):
        leases.clear()
        return {'owner':{'boot_id':str(uuid4()),'owner_generation':1}}
    async def goal(*args,**kwargs):sent.append(args)
    with pytest.raises(NavigationStopped):
        run(leases.send('rosy_01',SimpleNamespace(_get=get,navigation_goal=goal),{},1.,2.,0.,'attempt',task_id='task'))
    assert not sent


@pytest.mark.parametrize('withdraw_at', ['epoch', 'transport', 'negative_ack', 'wrong_boot'])
def test_native_rejection_before_send_releases_task_claim(tmp_path, withdraw_at):
    from fleet.server.goal_lease import GoalLeases
    from fleet.server.channel.execution.outcomes.task_receipt import prepare_send
    from fleet.swarm.dispatch_guard import check_dispatch
    store = FleetTaskStore(tmp_path / 'fleet.sqlite3')
    service = FleetTaskService(store, robot_ids={'rosy_01'})
    store.rearm_dispatch(expected_generation=store.dispatch_control()['generation'], actor_id='operator')
    run(service.submit_navigation(robot_id='rosy_01', x=1., y=2., source='operator',
                                  actor_id='op', request_key='rejected-native'))
    withdrawn, sent = [], []
    service.channel_admission = lambda tid: 'CHANNEL_WITHDRAWN' if withdrawn else None
    leases = GoalLeases(0, {})
    leases.prepare_send = partial(prepare_send, leases)
    leases.native_required = lambda tid: True
    leases.admit_attempt = service.admit_attempt
    leases.bind_native_receipt = service.bind_native_receipt

    async def get(path):
        if withdraw_at == 'epoch':
            withdrawn.append(True)
        return {'owner': {'boot_id': str(uuid4()), 'owner_generation': 1}}

    async def goal(*args, **kwargs):
        if withdraw_at == 'transport':
            withdrawn.append(True)
        check_dispatch(path='/api/v1/navigation/goal')
        sent.append(True)
        if withdraw_at == 'wrong_boot':
            return {'accepted': True, 'operation': {'boot_id': str(uuid4()), 'run_id': str(uuid4()),
                'kind': 'navigate', 'correlation_id': kwargs['correlation_id'], 'phase': 'SUBMITTED',
                'result': None, 'reason': None}}
        return {'accepted': False}

    async def dispatch(attempt):
        return await leases.send('rosy_01', SimpleNamespace(_get=get, navigation_goal=goal),
                                 {}, 1., 2., 0., attempt['attempt_id'], task_id=attempt['task_id'])

    result = run(service.dispatch_next({'rosy_01'}, dispatch=dispatch))
    if withdraw_at == 'wrong_boot':
        assert result['status'] == 'UNKNOWN'
        assert result['receipt'] == {'native_required': True}
        assert store.resource_claims(resource_kind='robot', resource_id='rosy_01')
        return
    assert result['status'] == ('FAILED' if withdraw_at == 'negative_ack' else 'HOLD')
    assert not (result['receipt'] or {}).get('native_required')
    assert not store.resource_claims(resource_kind='robot', resource_id='rosy_01')
    with store._connect() as conn:
        assert not conn.execute('SELECT 1 FROM fleet_robot_reservations').fetchall()
    assert bool(sent) == (withdraw_at == 'negative_ack')
