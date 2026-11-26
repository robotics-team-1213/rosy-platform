"""A keep-alive socket idle past the D-1073 server's 60 s timeout is replaced before the next request (2026-11-26)."""
import json
import sys
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))

import cell_remote_policy as crp  # noqa: E402

HEALTH = {"ok": True, "arms": {"arm_b": {"revision": "a" * 64, "views": {"top": [4, 4]}, "n_action_steps": 4, "chunk_size": 16}}}


def test_idle_connection_is_reopened_and_a_fresh_one_is_reused(monkeypatch):
    sh = crp.RemotePolicyShadow("http://127.0.0.1:8790", "arm_b", "a" * 64,
                                opener=lambda *_a, **_kw: BytesIO(json.dumps(HEALTH).encode()))
    sh._opener, sh._resolved_addrs = None, [("fam", "type", 0, ("127.0.0.1", 8790))]
    made = []
    monkeypatch.setattr(sh, "_connect_addr", lambda addr, timeout: made.append(Mock()) or made[-1])
    now = [1000.0]
    monkeypatch.setattr(crp.time, "monotonic", lambda: now[0])
    first = sh._ensure_conn()
    sh._used_at = now[0]
    now[0] += 10.0
    assert sh._ensure_conn() is first and len(made) == 1
    now[0] += crp.IDLE_RECONNECT_S + 1.0
    second = sh._ensure_conn()
    assert second is not first and len(made) == 2 and first.close.called
