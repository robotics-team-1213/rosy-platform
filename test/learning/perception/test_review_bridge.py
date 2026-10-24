"""Review-to-model-PC handoff without approvals or duplicate publication."""
from pathlib import Path
import shutil
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'learning/curation/perception'))
import review_bridge
from test_learning_cycle import make_review


def test_verified_export_published_once_and_incomplete_ignored(tmp_path):
    source = tmp_path / "incoming"
    source.mkdir()
    make_review(source)
    (source / "incomplete").mkdir()
    shutil.copytree(source / "export", source / ".partial-export")
    cfg = {"source": str(source), "peer": "approved-model-peer", "remote_reviews": "/srv/reviews",
           "interval_s": 3, "max_attempts": 2}
    calls = []
    fn = lambda *args: calls.append(args[1]) or {"training_dataset_qualified": False}
    review_bridge.run_once(cfg, tmp_path / "state", publisher=fn)
    shutil.copytree(source / "export", source / "duplicate")
    state = review_bridge.run_once(cfg, tmp_path / "state", publisher=fn)
    assert len(calls) == 1 and len(state["steps"]) == 1


def test_untrusted_bytes_never_reach_remote(tmp_path):
    source = tmp_path / "incoming"
    source.mkdir()
    export = make_review(source)
    (export / "inputs/images/000000.jpg").write_bytes(b"tampered")
    cfg = {"source": str(source), "peer": "approved-model-peer", "remote_reviews": "/srv/reviews",
           "interval_s": 3, "max_attempts": 2}
    state = review_bridge.run_once(cfg, tmp_path / "state",
                                  publisher=lambda *args: pytest.fail("do not publish"))
    assert not state["steps"] and state["errors"]


def test_network_failure_retries_then_stops_without_blocking_other_exports(tmp_path):
    source = tmp_path / "incoming"
    source.mkdir()
    make_review(source)
    cfg = {"source": str(source), "peer": "approved-model-peer", "remote_reviews": "/srv/reviews",
           "interval_s": 3, "max_attempts": 2}
    calls = []
    def fail(*args):
        calls.append(args)
        raise OSError("offline")
    for _ in range(3):
        state = review_bridge.run_once(cfg, tmp_path / "state", publisher=fail)
    assert len(calls) == 2
    assert next(iter(state["steps"].values()))["status"] == "failed"


def state_authority(store, folder=0o700, db=0o600, **change):
    import os
    import review_evidence
    os.chmod(store.state, folder); os.chmod(store.state / "reviews.sqlite3", db)
    value = {"state": str(store.state), "workspace_id": review_evidence.metadata(store, "workspace_id")}
    return dict(value, **change)


def test_state_authority_matches_http_document_byte_for_byte(tmp_path):
    import threading
    from urllib.request import urlopen
    from review_decisions import make_decisions_server
    from test_review_app import open_store
    store = open_store(tmp_path)
    server = make_decisions_server(store, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}/api/decisions"
    try:
        with urlopen(endpoint) as response:
            served = response.read()
        by_endpoint = review_bridge.fetch_current({"authority": {"endpoint": endpoint, "workspace_id": "x"}})
    finally:
        server.shutdown(); server.server_close(); thread.join()
    by_state = review_bridge.fetch_current({"authority": state_authority(store)})
    import json
    assert json.dumps(by_state).encode() == served
    assert by_state == by_endpoint


def test_state_authority_opens_database_read_only(tmp_path):
    import sqlite3
    from test_review_app import open_store
    store = open_store(tmp_path)
    database = store.state / "reviews.sqlite3"
    authority = state_authority(store)
    def tables():
        with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
            return sorted(r[0] for r in db.execute("SELECT name FROM sqlite_master"))
    before = (database.stat().st_mtime_ns, database.stat().st_size, tables(),
              sorted(p.name for p in store.state.iterdir()))
    review_bridge.fetch_current({"authority": authority})
    assert (database.stat().st_mtime_ns, database.stat().st_size, tables(),
            sorted(p.name for p in store.state.iterdir())) == before


@pytest.mark.parametrize("case", ["both", "neither"])
def test_authority_requires_exactly_one_of_endpoint_or_state(tmp_path, case):
    source = tmp_path / "incoming"; source.mkdir()
    authority = {"workspace_id": "w"}
    if case == "both":
        authority.update(endpoint="http://127.0.0.1:1/api/decisions", state=str(tmp_path))
    cfg = {"source": str(source), "peer": "approved-model-peer", "remote_reviews": "/srv/reviews",
           "interval_s": 3, "max_attempts": 2, "authority": authority}
    with pytest.raises(review_bridge.JobError, match="exactly one"):
        review_bridge.run_once(cfg, tmp_path / "bridge")


@pytest.mark.parametrize("case", ["relative", "symlink", "dotdot", "workspace", "missing"])
def test_state_authority_refuses_unsafe_or_foreign_state(tmp_path, case, monkeypatch):
    from test_review_app import open_store
    store = open_store(tmp_path)
    authority = state_authority(store)
    if case == "relative":
        monkeypatch.chdir(tmp_path)
        authority["state"] = "state"
    elif case == "symlink":
        link = tmp_path / "linked"; link.symlink_to(store.state, target_is_directory=True)
        authority["state"] = str(link)
    elif case == "dotdot":
        authority["state"] = str(store.state / ".." / "state")
    elif case == "workspace":
        authority["workspace_id"] = "other-workspace"
    else:
        authority["state"] = str(tmp_path / "absent")
    with pytest.raises(review_bridge.JobError):
        review_bridge.fetch_current({"authority": authority})
    assert not (tmp_path / "absent").exists()


def test_bridge_once_reads_state_authority_and_delivers_export(tmp_path):
    import json
    import subprocess
    import review_evidence
    from test_review_app import open_store
    store = open_store(tmp_path)
    store.prepare()
    destination = tmp_path / "received"
    cfg = {"source": str(store.state / "exports"), "peer": "local", "remote_reviews": str(destination),
           "transport": "local", "interval_s": 3, "max_attempts": 2, "authority": state_authority(store)}
    (tmp_path / "bridge.json").write_text(json.dumps(cfg))
    script = Path(review_bridge.__file__).resolve()
    # The model PC unit runs the bridge with -E -s; its imports must not need PYTHONPATH.
    result = subprocess.run([sys.executable, "-E", "-s", str(script), str(tmp_path / "bridge.json"),
                             "--out", str(tmp_path / "bridge"), "--once"], cwd=tmp_path,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.splitlines()[-1])
    assert report["errors"] == {} and list(report["exports"].values()) == ["done"]
    delivered = json.loads((destination / ".authority/current.json").read_text())
    assert delivered["available"] is True
    assert delivered["authority"] == review_evidence.decisions(store)


@pytest.mark.parametrize("folder,db,sidecar", [(0o755, 0o600, None), (0o700, 0o644, None),
                                               (0o755, 0o644, None), (0o700, 0o600, 0o644)])
def test_state_authority_refuses_group_or_other_permissions(tmp_path, folder, db, sidecar):
    import os
    from test_review_app import open_store
    store = open_store(tmp_path)
    authority = state_authority(store, folder, db)
    if sidecar is not None:
        journal = store.state / "reviews.sqlite3-journal"
        journal.write_bytes(b""); os.chmod(journal, sidecar)
    with pytest.raises(review_bridge.JobError, match="owner-only") as error:
        review_bridge.fetch_current({"authority": authority})
    assert str(store.state) not in str(error.value)


def test_state_authority_accepts_owner_only_permissions(tmp_path):
    import review_evidence
    from test_review_app import open_store
    store = open_store(tmp_path)
    current = review_bridge.fetch_current({"authority": state_authority(store, 0o700, 0o600)})
    assert current == review_evidence.decisions(store)


def test_state_authority_refuses_wal_database(tmp_path):
    import sqlite3
    from test_review_app import open_store
    store = open_store(tmp_path)
    database = store.state / "reviews.sqlite3"
    db = sqlite3.connect(database)
    assert db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    db.close()
    authority = state_authority(store)
    with pytest.raises(review_bridge.JobError, match="WAL"):
        review_bridge.fetch_current({"authority": authority})
