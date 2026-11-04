"""D-969 step 5: the Isaac side of a learned policy, with a fake server (no LeRobot on test hosts)."""
import hashlib
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import demo_units  # noqa: E402
from policy_client import PolicyClient  # noqa: E402

FAKE = '''
import json, sys
print(json.dumps({"ready": True, "state_dim": 12}), flush=True)
for line in sys.stdin:
    r = json.loads(line)
    image = r.get("images", {}).get("top", {})
    print(json.dumps({"ok": True} if r["op"] == "reset" else {"action": [v + 1 for v in r["state"]], "shape": image.get("shape")}), flush=True)
'''


def store(tmp_path, weights=b'weights'):
    sha = hashlib.sha256(weights).hexdigest()
    (tmp_path/'policies'/sha).mkdir(parents=True)
    (tmp_path/'policies'/sha/'model.safetensors').write_bytes(weights)
    (tmp_path/'server.py').write_text(FAKE, encoding='utf-8')
    return dict(env='unused', model_sha256=sha)


def test_units_round_trip_both_arms():
    radians = [.1, -.4, .3, 1.2, -.2, .35, -.1, .2, -.3, .9, .4, .5]
    back = demo_units.to_radians(demo_units.to_units(radians))
    assert back[:5] == pytest.approx(radians[:5], abs=2e-3) and back[6:11] == pytest.approx(radians[6:11], abs=2e-3)
    assert back[5] == pytest.approx(radians[5], abs=1e-3) and back[11] == pytest.approx(radians[11], abs=1e-3)


def test_client_runs_only_the_pinned_bytes_and_passes_images(tmp_path):
    spec = store(tmp_path)
    client = PolicyClient(spec, store=tmp_path, python=sys.executable, server=tmp_path/'server.py', device='cpu')
    try:
        client.reset()
        assert client.act([0.]*12, {'top': np.zeros((24, 32, 3), np.uint8)}) == [1.]*12
    finally:
        client.close()
    (tmp_path/'policies'/spec['model_sha256']/'model.safetensors').write_bytes(b'other')
    with pytest.raises(ValueError, match='bytes differ'):
        PolicyClient(spec, store=tmp_path, python=sys.executable, server=tmp_path/'server.py')
