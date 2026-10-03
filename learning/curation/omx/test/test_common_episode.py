"""Common Episode wrapper retains validated OMX bytes and separate clocks."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
for path in (ROOT / "contracts/learning/src", ROOT / "src/products/omx/adapter",
             ROOT / "src/contracts/foundation", ROOT / "src/products/omx/adapter/test",
             ROOT / "learning/curation/omx"):
    sys.path.insert(0, str(path))

from test_demonstration import complete_episode
from common_episode import convert
from rosy.contracts.learning import validate_episode


def test_common_episode_roundtrip_keeps_source_clock_action_and_unknowns(tmp_path):
    original = tmp_path / "recordings"
    manifest = complete_episode(original)
    source = original / manifest["episode_id"]
    before = {p.relative_to(source).as_posix(): p.read_bytes() for p in source.rglob('*') if p.is_file()}
    output = tmp_path / "common"
    doc = convert(source, output)
    assert validate_episode(doc, root=output)["revision"] == doc["revision"]
    assert doc["outcome"]["task"] == "success" and doc["outcome"]["judge"] == "operator"
    assert doc["outcome"]["action"] == "unknown"
    assert doc["revisions"]["policy"] is None
    samples = [json.loads(row) for row in (output/'source/samples.jsonl').read_text().splitlines()]
    assert samples[0]["capture_time_ns"] == 1_000_000_000
    assert samples[0]["received_at_ns"] == 1_000_000_010
    assert samples[0]["action"] == [.02, -.1]
    assert all((source / p).read_bytes() == value == (output / 'source' / p).read_bytes()
               for p, value in before.items())
    with pytest.raises(ValueError, match="new directory"):
        convert(source, output)


def test_tampered_omx_source_refused_before_common_output(tmp_path):
    original = tmp_path / "recordings"
    manifest = complete_episode(original)
    source = original / manifest["episode_id"]
    (source / 'samples.jsonl').write_text('{}\n')
    output = tmp_path / "common"
    with pytest.raises(ValueError, match="hash"):
        convert(source, output)
    assert not output.exists()
