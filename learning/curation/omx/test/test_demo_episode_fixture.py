"""The learning-owned episode generator writes what the contract validator accepts (not omx recorder code)."""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / 'contracts/learning/src'), str(Path(__file__).parent)]
from demo_episode_fixture import complete_episode, complete_episode_with, gripper_provenance, sample, EpisodeWriter, provenance
from rosy.contracts.learning.omx import validate_demonstration


@pytest.mark.parametrize('source', [None, 'gripper'])
def test_generated_episode_passes_the_contract_validator(tmp_path, source):
    manifest = complete_episode(tmp_path) if source is None else complete_episode_with(tmp_path, gripper_provenance())
    checked = validate_demonstration(tmp_path / manifest['episode_id'])
    assert checked['manifest']['status'] == 'complete' and len(checked['samples']) == 2
    assert checked['samples'][0]['action'] == [0.02, -0.1]
    assert ('action.gripper' in checked['samples'][0]) is (source == 'gripper')


def test_contract_validator_still_rejects_a_tampered_generated_episode(tmp_path):
    manifest = complete_episode(tmp_path)
    path = tmp_path / manifest['episode_id']
    (path / 'images/front/000000.png').write_bytes(b'x')
    with pytest.raises(ValueError):
        validate_demonstration(path)


def test_generator_matches_the_omx_recorder_file_layout(tmp_path):
    manifest = complete_episode(tmp_path)
    path = tmp_path / manifest['episode_id']
    assert sorted(p.name for p in path.iterdir()) == ['events.jsonl', 'images', 'manifest.json', 'samples.jsonl']
    assert [p.name for p in (path / 'images/front').iterdir()] == ['000000.png', '000001.png']
