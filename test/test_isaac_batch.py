"""A batch splits runs across simulation hosts and a rerun redoes only what is unfinished."""
import importlib.util
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
SHA = 'a' * 40


def module():
    sys.path.insert(0, str(ROOT / 'tools/remote'))
    spec = importlib.util.spec_from_file_location('isaac_batch', ROOT / 'tools/remote/isaac_batch.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Host:
    """Fake host: ready unless busy; each started run ends with the next status."""

    def __init__(self, role, *, busy=False, statuses=('SUCCEEDED',)):
        self.role, self.target_id, self.busy = role, role * 8, busy
        self.statuses, self.started, self.calls, self.runs = list(statuses), [], [], {}

    def prepare(self, sha):
        pass

    def hold(self, run_id, active):
        pass

    def call(self, sha, payload):
        self.calls.append(payload['action'])
        if payload['action'] == 'check':
            return {'input_sha256': 'c' * 64, 'ready': not self.busy, 'reason': 'GPU busy'}
        if payload['action'] == 'start':
            run = uuid.uuid5(uuid.NAMESPACE_URL, 'rosy.isaac-run:' + payload['request']['request_id']).hex
            self.started.append(payload['request']['config']['name'])
            self.runs[run] = self.statuses[0] if len(self.statuses) == 1 else self.statuses.pop(0)
            return {'run_id': run, 'input_sha256': 'c' * 64, 'status': 'PENDING'}
        return {'run_id': payload['run_id'], 'input_sha256': 'c' * 64,
                'status': self.runs.get(payload['run_id'], 'SUCCEEDED')}


def plan(*names):
    return {'scenario': 'omx-f-import', 'sha': SHA, 'runs': {n: {'name': n} for n in names}}


def run(mod, value, out, hosts, **kw):
    return mod.run_batch(value, out, hosts, sleep=lambda s: None, summarize=lambda r: r,
                         fetch=lambda receipt, remote, dest: dest / 'snap', log=lambda line: None, **kw)


def test_runs_split_across_hosts_and_a_rerun_skips_done(tmp_path):
    mod, value = module(), plan('a', 'b', 'c', 'd')
    model, ai = Host('model'), Host('ai')
    assert set(run(mod, value, tmp_path, [model, ai]).values()) == {'done'}
    assert sorted(model.started + ai.started) == ['a', 'b', 'c', 'd']
    assert json.loads((tmp_path / 'a/result.json').read_text())['role'] in ('model', 'ai')
    again = Host('model')
    run(mod, value, tmp_path, [again])
    assert again.started == []


def test_a_started_run_is_resumed_on_its_owner_not_started_again(tmp_path):
    mod, value = module(), plan('a')
    model = Host('model', statuses=('RUNNING',))
    run(mod, value, tmp_path, [model], max_polls=2)  # still running when polling stops: receipt kept, no result
    assert mod.state(tmp_path / 'a') == 'started'
    other = Host('ai')
    run(mod, value, tmp_path, [other])
    assert other.calls == [] and mod.state(tmp_path / 'a') == 'started'  # not the owner: left alone
    model.runs = {k: 'SUCCEEDED' for k in model.runs}
    model.calls.clear()
    assert run(mod, value, tmp_path, [model]) == {'a': 'done'}
    assert 'start' not in model.calls and model.started == ['a']


def test_an_unknown_run_is_set_aside_and_retried_not_polled_forever(tmp_path):
    mod, value = module(), plan('a')
    model = Host('model', statuses=('UNKNOWN', 'UNKNOWN', 'SUCCEEDED'))
    assert run(mod, value, tmp_path, [model]) == {'a': 'done'}
    assert model.started == ['a', 'a', 'a'] and (tmp_path / 'a.stale-2').is_dir()
    stuck = Host('model', statuses=('UNKNOWN',))
    assert run(mod, plan('b'), tmp_path, [stuck], job_errors=2) == {'b': 'new'}  # bounded by job_errors
    assert stuck.started == ['b', 'b']


def test_a_busy_host_retires_and_the_other_takes_its_share(tmp_path):
    mod, value = module(), plan('a', 'b', 'c')
    busy, model = Host('ai', busy=True), Host('model')
    assert set(run(mod, value, tmp_path, [busy, model], attempts=1).values()) == {'done'}
    assert busy.started == [] and sorted(model.started) == ['a', 'b', 'c']


def test_a_never_started_directory_is_set_aside(tmp_path):
    mod, value = module(), plan('a')
    (tmp_path / 'a').mkdir()
    (tmp_path / 'a/request.json').write_text('{}')
    model = Host('model')
    assert run(mod, value, tmp_path, [model]) == {'a': 'done'}
    assert (tmp_path / 'a.stale-1/request.json').is_file()


def test_a_grid_plan_expands_to_case_seed_runs():
    value = module().expand({'scenario': 'x', 'sha': SHA, 'config': {'layers': 3}, 'case_prefix': 'n-',
                             'cases': ['g315', 'y020'], 'seeds': [42, 43]})
    assert value['runs']['y020-s43'] == {'layers': 3, 'seed': 43, 'case': 'n-y020'} and len(value['runs']) == 4


def test_pause_accepts_unit_names_only():
    mod = module()
    assert mod.pauses(['ai=rosy-ollama.service,b.service']) == {'ai': ['rosy-ollama.service', 'b.service']}
    for bad in ('ai=x; rm -rf ~.service', 'site=a.service', 'ai=a.timer'):
        try:
            mod.pauses([bad])
        except ValueError:
            continue
        raise AssertionError(bad)


class Lending(Host):
    """A host whose role service lends the GPU only while `idle` is set."""

    def __init__(self, role, idle):
        super().__init__(role)
        self.idle, self.lent = idle, []

    def tenants(self, action, units):
        self.lent.append(action)
        if action == 'claim':
            return 'claimed' if self.idle else 'busy robot online'
        return 'released'


def test_a_run_borrows_the_role_gpu_only_while_the_role_is_idle(tmp_path):
    mod, value = module(), plan('a', 'b')
    working, idle = Lending('ai', idle=False), Lending('model', idle=True)
    states = run(mod, value, tmp_path, [working, idle], attempts=1, lend={'ai': ['o.service'], 'model': ['o.service']})
    assert set(states.values()) == {'done'} and working.started == [] and sorted(idle.started) == ['a', 'b']
    assert idle.lent.count('claim') == 2  # borrowed before each run, not once per batch


def test_lent_units_are_handed_back_even_when_the_batch_fails():
    mod, host = module(), Lending('ai', idle=True)

    def fail():
        raise ConnectionError('lost')
    try:
        mod.service_window([host], {'ai': ['o.service']}, fail, log=lambda line: None)
    except ConnectionError:
        pass
    assert host.lent == ['release']


def test_summary_row_shows_placed_and_worst_box():
    detail = {'role': 'ai', 'status': 'FAILED', 'summary': {'placed': 2, 'planned': 9, 'failures': ['f'],
              'unstable': [{'box': 1, 'position_error_mm': 1.1}, {'box': 0, 'position_error_mm': .2}]}}
    assert module().row('a', 'done', detail).split('\t') == ['a', 'done', 'ai', 'FAILED', '2/9', 'box1 1.1 mm', 'f']
