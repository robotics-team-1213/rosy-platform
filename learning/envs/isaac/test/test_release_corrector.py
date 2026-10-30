"""The release corrector learns the IK teacher's packed-release command from noisy state, not from images."""
import copy
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import mapped_stack_fixture as f
import release_corrector as rc
from test_container_stack import bodies, held_scene


def released_report(fixture, index=1):
    """A report whose layer `index` went through two feedback iterations and settled."""
    carry = dict(held_scene(fixture, index), tick=0)
    after = [dict(copy.deepcopy(carry), tick=12), dict(copy.deepcopy(carry), tick=24)]
    commands = [f.cube_release_target(index, s, .05, fixture=fixture) for s in [carry, after[0]]]
    rested = dict(boxes=copy.deepcopy(bodies(fixture)), tcps=carry['tcps'])
    settle = [dict(copy.deepcopy(rested), tick=100+12*k) for k in range(13)]
    layers = [{} for _ in range(index)] + [dict(carry_sample=carry, release_samples=after, release_commands=commands,
                                              opened_sample=after[-1], settle_samples=settle)]
    return dict(fixture=fixture, trials=[dict(layers=layers)])


def test_demonstrations_are_the_teacher_command_minus_the_measured_tcp():
    fixture = f.container_fixture(layers=3, case='nominal')
    rows = rc.release_demonstrations(released_report(fixture))
    assert [r['iteration'] for r in rows] == [0, 1]
    assert all(len(r['observation']) == rc.FEATURES for r in rows)
    sample = held_scene(fixture, 1)
    expected = np.subtract(f.cube_release_target(1, sample, .05, fixture=fixture), sample['tcps'][0])
    assert rows[0]['action'] == pytest.approx(expected.tolist())
    assert rows[0]['outcome']['stable'] is True and rows[0]['outcome']['position_error_mm'] == pytest.approx(0.)


def test_augmented_rows_recompute_the_teacher_and_bound_the_observation_noise():
    fixture = f.container_fixture(layers=3, case='nominal')
    sample = held_scene(fixture, 1)
    rng = np.random.default_rng(3)
    rows = [rc.augment(sample, 1, fixture, rng) for _ in range(200)]
    kept = [r for r in rows if r is not None]
    assert len(kept) > 150  # few perturbations push the outer footprint past the envelope
    for obs, clean, action, truth in kept[:20]:
        expected = np.subtract(f.cube_release_target(1, truth, .05, fixture=fixture), truth['tcps'][0])
        assert action == pytest.approx(expected.tolist())
        noise = np.abs(np.subtract(obs[:3], clean[:3]))
        assert noise.max() <= .005 + 1e-12  # held-box position estimate error stays within 5 mm
    assert rc.augment(sample, 1, fixture, np.random.default_rng(3)) == rows[0]


def test_bc_model_beats_the_mean_and_survives_save_and_load(tmp_path):
    fixture = f.container_fixture(layers=3, case='nominal')
    rng = np.random.default_rng(0)
    data = [r for r in (rc.augment(held_scene(fixture, i), i, fixture, rng) for i in (1, 2) * 400) if r]
    x = np.array([r[0] for r in data]); y = np.array([r[2] for r in data])
    model = rc.MLP.fit(x[:600], y[:600], epochs=400, seed=0)
    error = np.abs(model.predict(x[600:]) - y[600:]).mean()
    baseline = np.abs(y[:600].mean(0) - y[600:]).mean()
    assert error < .5 * baseline
    digest = model.save(tmp_path / 'corrector.npz')
    again = rc.MLP.load(tmp_path / 'corrector.npz', digest)
    assert np.allclose(again.predict(x[600:]), model.predict(x[600:]))
    with pytest.raises(ValueError, match='sha256'):
        rc.MLP.load(tmp_path / 'corrector.npz', '0' * 64)


def test_train_writes_a_pinned_model_and_its_evidence_from_reports(tmp_path):
    import json
    fixture = f.container_fixture(layers=3, case='nominal')
    paths = []
    for index in (1, 2):
        path = tmp_path / f'report-{index}.json'
        path.write_text(json.dumps(released_report(fixture, index)))
        paths.append(path)
    paths.append(paths[0])  # a repeated deterministic run adds no new release
    meta = rc.train(paths, tmp_path / 'out', per_snapshot=150, seed=0, epochs=300)
    assert meta['releases'] == 2 and meta['snapshots'] == 4
    assert meta['holdout_mean_abs_error_mm'] < meta['holdout_mean_baseline_mm']
    model = rc.MLP.load(tmp_path / 'out' / 'release-corrector.npz', meta['sha256'])
    assert json.loads((tmp_path / 'out' / 'release-corrector.json').read_text()) == meta
    assert model.predict([meta and [0.] * rc.FEATURES]).shape == (1, 3)
    assert meta['scope'] == 'SIM_IK_TEACHER_BC_NOT_RL_NOT_HARDWARE'


BC_V0 = '85713c8ec54190e53729d6df73d5d59f3e6e7d715058bfb7698b3793042b9294'


@pytest.mark.parametrize('case', ['nominal-estimate', 'nominal-bc-v0'])
def test_evaluation_cases_see_a_noisy_held_box_and_pin_the_model(case):
    fixture = f.container_fixture(layers=3, case=case)
    nominal = f.container_fixture(layers=3, case='nominal')
    assert fixture['release_estimate_noise_m'] == [.002, .005]
    assert fixture['revision'] != nominal['revision']
    assert {k: v for k, v in fixture.items() if k not in ('revision', 'case', 'release_estimate_noise_m',
                                                          'release_corrector')} == \
        {k: v for k, v in nominal.items() if k not in ('revision', 'case')}
    if case == 'nominal-bc-v0':
        assert fixture['release_corrector'] == dict(file='release-corrector-bc-v0.npz', sha256=BC_V0)
        assert rc.load_corrector(fixture) is not None
    else:
        assert 'release_corrector' not in fixture and rc.load_corrector(fixture) is None


def test_estimate_moves_only_the_held_box_by_two_to_five_millimetres():
    fixture = f.container_fixture(layers=3, case='nominal-estimate')
    sample = held_scene(fixture, 1)
    rng = np.random.default_rng(5)
    for _ in range(50):
        estimate = rc.estimate(sample, 1, fixture, rng)
        moved = np.linalg.norm(np.subtract(estimate['boxes'][1]['position'], sample['boxes'][1]['position']))
        assert .002 - 1e-12 <= moved <= .005 + 1e-12
        assert estimate['boxes'][0] == sample['boxes'][0] and estimate['tcps'] == sample['tcps']


def test_corrector_command_is_the_tcp_plus_the_predicted_correction():
    fixture = f.container_fixture(layers=3, case='nominal-bc-v0')
    model = rc.load_corrector(fixture)
    sample = held_scene(fixture, 1)
    command = rc.corrector_command(model, sample, 1, fixture, 2)
    expected = np.add(sample['tcps'][0], model.predict([rc.observation(sample, 1, fixture, 2)])[0])
    assert command == pytest.approx(expected.tolist())
    teacher = f.cube_release_target(1, sample, .05, fixture=fixture)
    assert np.abs(np.subtract(command, teacher)).max() < .003  # the pinned BC model tracks the IK teacher
