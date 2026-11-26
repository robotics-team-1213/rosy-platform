"""Site release selection avoids repeating immutable ancestry checks."""

import json

from deploy.site import rosy_site_autoupdate as upd
from test_site_autoupdate import FakeHttp, NEW, NEWER, OLD, REPO, _bundle, _release, _tag


class CompareHttp(FakeHttp):
    def __init__(self):
        super().__init__([], {})
        self.compares = []

    def get(self, url, limit):
        base, head = url.split("/compare/")[1].split("?")[0].split("...")
        head_sha = next((sha for sha in (OLD, NEW, NEWER) if head == _tag(sha)), head)
        self.compares.append((base, head_sha))
        return json.dumps({
            "status": "ahead" if head_sha > base else "behind",
            "merge_base_commit": {"sha": min(base, head_sha)},
        }).encode()


def test_idle_selection_reuses_only_immutable_ancestor_comparisons(tmp_path):
    rows = [
        {**_release(commit, f"2026-10-04T0{n}:00:00Z", _bundle(commit)), "target_commitish": commit}
        for n, commit in enumerate((OLD, NEW, NEWER), 1)
    ]
    state = {"failed": {}}
    http = CompareHttp()
    updater = upd.SiteUpdater({"repo": REPO}, paths=upd.Paths(tmp_path), http=http)
    assert updater.select(rows, NEWER, state) is None
    assert http.compares == [(NEWER, NEW), (NEWER, OLD)]
    http.compares.clear()
    saved = json.loads(json.dumps(state))
    assert updater.select(rows, NEWER, saved) is None
    assert http.compares == []
    moved = NEW[:12] + "f" * 28
    assert updater.select([dict(rows[1], target_commitish=moved)], NEWER, saved) is None
    assert http.compares == [(NEWER, moved)]  # cache is keyed by the complete SHA
    http.compares.clear()
    assert updater.select(rows, NEW, saved)["tag_name"] == _tag(NEWER)
    assert http.compares == [(NEW, NEWER)]
