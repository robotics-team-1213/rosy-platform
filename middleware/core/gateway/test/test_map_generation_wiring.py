"""The docking manager gets the map generation as a direct provider (DockAnchor.map_generation), no getattr reach (C6 seam, test_module_criteria)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from core.drive import docking as wiring


def test_the_docking_manager_reads_the_state_map_generation_through_a_provider(tmp_path: Path):
    state = mock.MagicMock()
    state.map_generation = SimpleNamespace(value=41)
    with mock.patch.object(wiring, "DockingManager") as manager, mock.patch.object(wiring, "SwarmManager"):
        try:
            wiring.build_docking_and_swarm(simulation_docking=None, data_path=tmp_path, events=mock.MagicMock(), state=state, modes=mock.MagicMock(), command=mock.MagicMock(),
                                           safety=mock.MagicMock(), capability=mock.MagicMock(), battery=mock.MagicMock(), line_follow=mock.MagicMock(), nav=mock.MagicMock(),
                                           robot_id="robot-1")
        except Exception:  # noqa: BLE001 - only the keyword handed to the manager matters here; later wiring may need more than a mock
            pass
    provider = manager.call_args.kwargs["map_generation_provider"]
    assert provider() == 41
    state.map_generation.value = 42
    assert provider() == 42                                                           # read at call time, not frozen at wiring
