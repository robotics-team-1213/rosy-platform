"""Sweep grids and result handling run without the optional MuJoCo simulator."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def sweeps(monkeypatch):
    scene = SimpleNamespace()
    for name, module in [('ship_release_scene', scene), ('ship_container_variants', SimpleNamespace()),
                         ('ship_release_strategies', SimpleNamespace())]:
        monkeypatch.setitem(sys.modules, name, module)
    modules = []
    for path in ['tools/sim/ship_release_sweep.py', 'tools/sim/ship_release_strategy_sweep.py']:
        spec = importlib.util.spec_from_file_location(Path(path).stem, ROOT / path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    return scene, *modules


def test_release_sweep_grid_and_result(sweeps):
    scene, sweep, _ = sweeps
    cases = list(sweep.cases())
    assert len(cases) == 7056
    assert {(c['layer'], c['row']) for c in cases} == {(1, 1), (1, -1), (2, 1), (2, -1)}
    assert min(c['dy'] for c in cases) == -0.0015
    assert max(c['dy'] for c in cases) == max(c['dx'] for c in cases) == 0.0015
    scene.build = lambda layer: ('model', 'fixture')
    scene.run = lambda model, fixture, **kw: dict(z_mm=1.4)
    scene.verdict = lambda result, layer: ['rode-up'] if result['z_mm'] > 1 else []
    result = sweep.one(cases[0])
    assert all(result[k] == value for k, value in cases[0].items())
    assert result['fail'] == ['rode-up'] and result['z_mm'] == 1.4


def test_strategy_sweep_grid_and_contiguous_band(sweeps):
    _, _, sweep = sweeps
    main, clearance = list(sweep.cases('main')), list(sweep.cases('clearance'))
    assert len(main) == 3942 and len(clearance) == 1377
    assert {c['layer'] for c in main} == {1, 2}
    assert {c['clearance_mm'] for c in main} == {None}
    assert {c['layer'] for c in clearance} == {1}
    assert {c['gap'] for c in clearance} == {0.0315}
    assert {c['clearance_mm'] for c in clearance} == {0.2, 0.5, 1.0}
    assert sweep.signed([0, 0.5, 0.5]) == [-0.5, 0, 0.5]
    rows = [dict(dy=dy, seated=seated) for dy, seated in
            [(0, True), (-0.0005, True), (0.0005, False), (-0.001, True), (0.001, True)]]
    assert sweep.band(rows) == 0
    rows[2]['seated'] = True
    assert sweep.band(rows) == 1.0
