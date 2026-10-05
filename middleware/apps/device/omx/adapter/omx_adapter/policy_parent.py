"""Runner-scoped, process-local parent readback; not a dispatch or peer API."""
import json
import weakref

_MINT_TOKEN = object()
_MINTED = weakref.WeakSet()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def projection(snapshot):
    """Project the existing current D18 readback from one SQLite snapshot."""
    action, events = snapshot['action'], snapshot['events']
    payload = action['request']['payload']
    names = ('mission_id', 'step_id', 'action_id', 'attempt_id', 'workcell_id', 'instance_id',
             'request_digest', 'authority_epoch', 'dispatch_generation')
    result = {name: payload[name] for name in names}
    result.update(state=action['state'], driver_goal_id=action.get('driver_goal_id'),
                  journal_event_id=action['journal_event_id'], observed_at=action['updated_at'],
                  reason=action.get('reason'), created=False, phase_summaries=[])
    if len(snapshot['phases']) > 4:
        raise PermissionError('original phase bound exceeded')
    for phase in snapshot['phases']:
        matching = [event for event in events if event['attempt_id'] == action['attempt_id']
                    and event['event_type'].startswith('ACTION_PHASE_')
                    and event['detail'].get('phase_id') == phase['phase_id']]
        if not matching:
            raise PermissionError('phase has no original durable event')
        result['phase_summaries'].append(dict(phase_id=phase['phase_id'], ordinal=phase['ordinal'],
            state=phase['state'], journal_event_id=matching[-1]['event_id'], observed_at=phase['updated_at']))
    return result


class _ParentCapability:
    def __init__(self, reader, validator=None, *, token=None):
        if token is not _MINT_TOKEN:
            raise PermissionError('parent capability must be minted by the validated runner')
        self._reader = reader
        self._validator = validator
        _MINTED.add(self)

    def __reduce__(self):
        raise TypeError('parent capability is process-local and cannot be serialized')

    def snapshot(self):
        return self._reader()

    def validate(self):
        """Final authority check, with no SQLite read or result construction."""
        self._validator()


def mint_parent(runner, grant, *, peer_uid):
    """Requires the actual validated runner/store; identity text is insufficient."""
    from .action_runner import ActionRunner, DIRECT_DRIVER_KINDS, parse_action_grant
    if not isinstance(runner, ActionRunner):
        raise PermissionError('actual local Action runner required')
    grant = parse_action_grant(grant)
    store = runner.store
    principal = runner._principal(peer_uid)
    grant_bytes = encoded(grant.model_dump(mode='json'))
    file_stat = store.path.stat()
    file_identity = file_stat.st_dev, file_stat.st_ino
    provider_names = ('principal_for_peer', 'current_fence', 'capability_current', 'now')
    providers = tuple(getattr(runner, name) for name in provider_names)

    def validate():
        stat = store.path.stat()
        if (runner.store is not store or (stat.st_dev, stat.st_ino) != file_identity
                or runner.enabled is not True or runner._principal(peer_uid) != principal):
            raise PermissionError('original parent owner or store changed')
        if (grant.action_kind not in runner.phase_runner_factories
                and grant.action_kind not in DIRECT_DRIVER_KINDS):
            raise PermissionError('parent has no registered executor')
        runner._validate(grant)
        # Provider calls may block or mutate the clock/owner. The final sample
        # must follow every such call, not merely precede capability_current.
        final_principal = runner._principal(peer_uid)
        final_stat = store.path.stat()
        final_now = runner.now()
        if final_now.tzinfo is None or final_now.utcoffset() is None:
            raise RuntimeError('parent clock must return an aware timestamp')
        if (final_principal != principal or runner.enabled is not True or runner.store is not store
                or (final_stat.st_dev, final_stat.st_ino) != file_identity
                or tuple(getattr(runner, name) for name in provider_names) != providers
                or not grant.issued_at <= final_now < grant.expires_at):
            raise PermissionError('parent provider/owner changed or grant expired during validation')

    def read():
        validate()
        snapshot = store.attempt_snapshot(grant.action_id, grant.attempt_id)
        action = snapshot['action']
        if (action['principal_id'] != principal or action['workcell_id'] != grant.workcell_id
                or action['instance_id'] != grant.instance_id or action['action_kind'] != grant.action_kind
                or action['configuration_revision'] != grant.config_revision
                or action['owner_generation'] != grant.dispatch_generation
                or encoded(action['request']['payload']) != grant_bytes):
            raise PermissionError('original stored parent grant differs')
        events = snapshot['events']
        if (not events or events[0]['event_type'] != 'ACTION_PREPARED'
                or events[0]['actor_id'] != principal
                or any(event['event_type'] == 'PROCESS_RESTARTED_UNRESOLVED' for event in events)
                or not any(event['event_type'] == 'DRIVER_SUBMISSION_STARTED'
                           and event['attempt_id'] == grant.attempt_id for event in events)):
            raise PermissionError('parent lacks admitted submission history')
        validate()  # Slow storage I/O cannot hide expiration/revocation.
        return snapshot

    initial = read()
    if initial['action']['state'] not in {
            'SUBMITTING', 'ACCEPTED', 'RUNNING', 'CANCEL_REQUESTED', 'UNKNOWN', 'HOLD'}:
        raise PermissionError('only a live original attempt may mint a parent capability')
    original = encoded(initial['events'])
    creation = initial['action']['created_at']

    def pinned_read():
        snapshot = read()
        if (snapshot['action']['created_at'] != creation
                or encoded(snapshot['events'][:len(initial['events'])]) != original):
            raise PermissionError('original parent history changed or restarted')
        # Terminal readback is permitted only through the preterminal capability.
        return snapshot

    return _ParentCapability(pinned_read, validate, token=_MINT_TOKEN)
