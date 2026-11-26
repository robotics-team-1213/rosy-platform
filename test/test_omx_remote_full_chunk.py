"""The timed single-arm drive asks the D-1073 server for the whole chunk (2026-11-26: four 15 Hz rows were all late)."""
import json
import sys
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "robot" / "omx"))

import cell_remote_policy as crp  # noqa: E402

HEALTH = {"ok": True, "arms": {"arm_b": {"revision": "a" * 64, "views": {"top": [4, 4]}, "n_action_steps": 4, "chunk_size": 16}}}


def _shadow():
    return crp.RemotePolicyShadow("http://127.0.0.1:8790", "arm_b", "a" * 64,
                                  opener=lambda *_a, **_kw: BytesIO(json.dumps(HEALTH).encode()))


def test_full_chunk_flag_goes_on_the_infer_request_only_when_set():
    sent = []
    for flag in (None, True):
        sh = _shadow()
        if flag:
            sh.full_chunk = True

        def fake(method, route, body=None, sent=sent):
            sent.append(dict(body))
            return {"ok": True, "request_id": body["request_id"], "arm_id": "arm_b", "revision": "a" * 64, "chunk": [[0.0] * 6] * 16}

        sh._request_json = fake
        try:
            assert len(sh.infer({"state": [0.0] * 6}).chunk) == 16
        finally:
            sh.close()
    assert "full_chunk" not in sent[0] and sent[1]["full_chunk"] is True
