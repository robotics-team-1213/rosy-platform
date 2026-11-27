"""Site auto-update: a candidate whose reused base images are absent is skipped, not failed."""
import json
from pathlib import Path

from deploy.site import rosy_site_autoupdate as upd
from deploy.site.verify_candidate import MissingBaseImageError
from test_site_autoupdate import (NEW, NEWER, OLD, REPO, FakeHost, FakeHttp, _tag, _verifier,  # noqa: F401
                                  _world, host)


def test_missing_reused_base_skips_candidate_and_falls_through(host):
    releases, blobs = _world((OLD, '2026-10-04T01:00:00Z'), (NEW, '2026-10-04T02:00:00Z'), (NEWER, '2026-10-04T03:00:00Z'))
    fake, inner = FakeHost(host.paths), _verifier([], ())

    def verify(folder, **kwargs):
        if Path(folder).name == NEWER and kwargs['inspect_loaded_images']:
            raise MissingBaseImageError('docker image inspection failed for fleet')
        return inner(folder, **kwargs)
    updater = upd.SiteUpdater(host.config, paths=host.paths, runner=fake, http=FakeHttp(releases, blobs),
                              verifier=verify, sleep=lambda seconds: None, clock=iter(range(0, 100000, 10)).__next__)
    assert updater.run() == upd.EXIT_OK
    state = json.loads(host.paths.state.read_text())
    assert state['installed']['commit'] == NEW
    assert state['skipped_base'][_tag(NEWER)]['current'] == OLD
    assert _tag(NEWER) not in state['failed']
    # Skipped only while the running commit is unchanged; a new running commit retries it.
    assert updater.select(releases, OLD, state)['tag_name'] == _tag(NEW)
    assert updater.select(releases, NEW, state)['tag_name'] == _tag(NEWER)
