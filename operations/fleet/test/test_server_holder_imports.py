"""D-798: a file moved into a server holder still imports under its old ``fleet.server.<name>``."""
import ast
import importlib
import importlib.util
from pathlib import Path

from fleet._source_layout import SERVER_HOLDERS, SOURCE_ROOTS

FLEET_ROOT = Path(__file__).resolve().parents[1] / "fleet"
SERVER = FLEET_ROOT / "server"
ACCOUNT = SERVER.parents[2] / "account" / "rosy_account"
SITUATION = SOURCE_ROOTS["assessment"] / "rosy_situation"
FLEET_SOURCES = SERVER.parents[3] / "tools" / "packaging" / "fleet_sources.py"
ACCOUNT_ALIASES = frozenset({
    "account_authority", "password_session", "site_users",
})


def _assessment_modules() -> tuple[str, ...]:
    tree = ast.parse(FLEET_SOURCES.read_text(encoding="utf-8"), filename=str(FLEET_SOURCES))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "ASSESSMENT_MODULES":
                    return tuple(ast.literal_eval(node.value))
    raise AssertionError("ASSESSMENT_MODULES not found in tools/packaging/fleet_sources.py")


def _rosy_situation_imports(path: Path, *, inside_rosy_situation: bool) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if parts[0] == "rosy_situation":
                    found.add(parts[1] if len(parts) > 1 else "__init__")
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0 and inside_rosy_situation:
                if node.module:
                    found.add(node.module.split(".")[0])
                else:
                    for alias in node.names:
                        if (SITUATION / f"{alias.name}.py").is_file():
                            found.add(alias.name)
            elif node.level == 0 and node.module:
                parts = node.module.split(".")
                if parts[0] == "rosy_situation":
                    found.add(parts[1] if len(parts) > 1 else "__init__")
                    if len(parts) == 1:
                        for alias in node.names:
                            if (SITUATION / f"{alias.name}.py").is_file():
                                found.add(alias.name)
    return found


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


def test_fleet_assessment_modules_cover_internal_and_fleet_imports():
    assessment_modules = _assessment_modules()
    allowed = set(assessment_modules)
    assert "__init__" in allowed

    missing: dict[str, list[str]] = {}
    for module in assessment_modules:
        path = SITUATION / f"{module}.py"
        assert path.is_file(), f"Missing packaged rosy_situation module: {path}"
        imported = _rosy_situation_imports(path, inside_rosy_situation=True)
        outside = sorted(imported - allowed)
        if outside:
            missing[str(path.relative_to(SERVER.parents[3]))] = outside

    for path in sorted(FLEET_ROOT.rglob("*.py")):
        imported = _rosy_situation_imports(path, inside_rosy_situation=False)
        outside = sorted(imported - allowed)
        if outside:
            missing[str(path.relative_to(SERVER.parents[3]))] = outside

    assert not missing, f"rosy_situation imports outside ASSESSMENT_MODULES: {missing}"

