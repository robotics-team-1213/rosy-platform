"""Synthetic fixtures exercise dynamic model signatures without claiming device evidence."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.mark.parametrize('arms,cameras', [(1, 1), (2, 3), (3, 4)])
def test_generated_fixture_is_deterministic_and_hil_ready(tmp_path, arms, cameras):
    from experiment_dataset import load_dataset
    from experiment_smoke import generate
    first, second = tmp_path / 'first', tmp_path / 'second'
    generate(first, arms=arms, cameras=cameras)
    generate(second, arms=arms, cameras=cameras)
    one, two = load_dataset(first, method='hilserl'), load_dataset(second, method='hilserl')
    assert one.source == 'synthetic_smoke'
    assert len(one.profile['arms']) == arms
    assert len(one.profile['cameras']) == cameras
    assert one.revision == two.revision
    assert len(one.split('train')) == len(one.split('eval')) == 1
    for episode in one.episodes:
        assert episode.arrays['action'].shape == (10, arms * 3)
        assert set(episode.arrays['is_intervention'].tolist()) == {True, False}
        assert np.all(episode.arrays['next_state'][:-1] == episode.arrays['observation.state'][1:])
        assert episode.arrays['terminated'][-1]


@pytest.mark.parametrize('arms,cameras', [(0, 1), (1, 0), (33, 1), (1, 65), (True, 1)])
def test_invalid_sizes_create_no_output(tmp_path, arms, cameras):
    from experiment_smoke import generate
    output = tmp_path / 'output'
    with pytest.raises(ValueError):
        generate(output, arms=arms, cameras=cameras)
    assert not output.exists()


def test_existing_output_is_never_modified(tmp_path):
    from experiment_smoke import generate
    marker = tmp_path / 'keep'
    marker.write_text('original')
    with pytest.raises(ValueError):
        generate(tmp_path)
    assert marker.read_text() == 'original'
