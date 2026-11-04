"""v11 ship hold and container v2 geometry (ship_v11.py): sockets over pins, the documented gaps, pieces per container."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ship_v11 as v11  # noqa: E402


def test_geometry_matches_the_ship_and_container_cad():
    assert v11.self_check()


def test_upper_containers_keep_only_the_end_sockets():
    full, ends = v11.container_pieces(), v11.container_pieces(ends_only=True)
    sockets = lambda pieces: sum(1 for p in pieces if p[2] == 'socket')//v11.SEGMENTS
    cones = lambda pieces: sum(1 for p in pieces if p[2] == 'cone')
    assert (sockets(full), sockets(ends), cones(full), cones(ends)) == (12, 4, 4, 4)


def test_targets_stack_by_the_container_stacking_height():
    z = [v11.target(1, layer)[2] for layer in range(3)]
    assert abs(z[1]-z[0]-v11.HEIGHT*v11.MM) < 1e-12 and abs(z[0]-(v11.FLOOR+v11.HEIGHT/2)*v11.MM) < 1e-12
