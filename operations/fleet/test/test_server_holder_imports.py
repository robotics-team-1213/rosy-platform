"""D-798: a file moved into a server holder still imports under its old ``fleet.server.<name>``."""
import importlib
import importlib.util
from pathlib import Path

from fleet._source_layout import SERVER_HOLDERS

SERVER = Path(__file__).resolve().parents[1] / "fleet" / "server"
ACCOUNT = SERVER.parents[2] / "account" / "rosy_account"
ACCOUNT_ALIASES = frozenset({
    "account_authority", "password_session", "site_users",
})


def test_every_holder_file_resolves_under_fleet_server():
    moved = [p for holder in SERVER_HOLDERS for p in (SERVER / holder).glob("*.py")]
    assert {"proposal_store.py", "map_pose_service.py", "identity.py", "traffic.py", "site_map_store.py"} <= {
        p.name for p in moved}
    for path in moved:
        name = f"fleet.server.{path.stem}"
        expected = path
        if path.parent.name == "auth" and path.stem in ACCOUNT_ALIASES:
            canonical = importlib.import_module(f"rosy_account.{path.stem}")
            assert importlib.import_module(name) is canonical, path
            expected = ACCOUNT / path.name
            assert Path(canonical.__file__).resolve() == expected.resolve(), path
        spec = importlib.util.find_spec(name)
        assert spec is not None and Path(spec.origin).resolve() == expected.resolve(), path


def test_old_import_path_loads_the_moved_module():
    from fleet.server import map_pose_service, proposal_store
    assert Path(proposal_store.__file__).parent.name == "evidence"
    assert Path(map_pose_service.__file__).parent.name == "pose"
