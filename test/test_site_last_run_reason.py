"""last_run.reason carries only our own fixed text, never command output."""
import json
from types import SimpleNamespace

from deploy.site import rosy_site_autoupdate as upd
from test_site_autoupdate import FakeHost, FakeHttp, _updater, host  # noqa: F401 - host is a fixture


class _RefusedPs(FakeHost):
    def __call__(self, args, **kwargs):
        if args[:2] == ['docker', 'compose'] and 'ps' in args and '--hash' not in args:
            return SimpleNamespace(returncode=1, stdout='', stderr='LEAKED-STDERR-DETAIL')
        return super().__call__(args, **kwargs)


def test_last_run_reason_never_carries_command_output(host):
    updater = _updater(host, FakeHttp([], {}), _RefusedPs(host.paths))
    assert updater.run() == upd.EXIT_FAILED
    last = json.loads(host.paths.state.read_text())['last_run']
    assert last['result'] == 'refused' and last.get('reason')
    assert 'LEAKED-STDERR-DETAIL' not in json.dumps(last)
