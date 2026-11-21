"""Ship hold task cards: all 18 spots (h1/h2 x r0-r2 x l0-l2) exist, load through the bench's card reader, and state reach honestly."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / 'deploy/robot/omx') not in sys.path:
    sys.path.insert(0, str(ROOT / 'deploy/robot/omx'))
import ship_task_cards  # noqa: E402
from bench_record_inspect import _read_task_card  # noqa: E402


def test_every_ship_spot_has_a_valid_card(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['x', '--out', str(tmp_path), '--root-prefix', '/tmp/omx'])
    ship_task_cards.main()
    files = sorted(tmp_path.glob('*.yaml'))
    assert len(files) == 18
    cards = [_read_task_card(p) for p in files]
    assert all(c['valid'] for c in cards), [c for c in cards if not c['valid']]
    expected = {f'ship-h{h}r{r}-l{l}' for h in (1, 2) for r in range(3) for l in range(3)}
    assert {c['target_slot'] for c in cards} == expected and {c['origin'] for c in cards} == {'belt'}
    assert len({c['task_id'] for c in cards}) == 18
    for c in cards:
        assert c['task_id'] == f"belt-to-{c['target_slot']}"
        h, r, l = c['target_slot'][len('ship-h')], c['target_slot'][-4], c['target_slot'][-1]
        assert f'hold h{h}' in c['single_task'] and f'(r{r})' in c['single_task'] and f'(l{l})' in c['single_task']
        assert ('shot_arm' in c) == c['target_slot'].startswith('ship-h1')
        assert '도달 미검증(planned_unverified)' in c['raw']
