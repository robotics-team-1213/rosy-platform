"""Pack affected pytest paths without cross-suite module-cache collisions."""

# Leave room for the remote runner's SSH command and options.
MAX_INVOCATION_CHARS = 3000
IGNORED_BASENAMES = frozenset({'__init__.py', 'conftest.py'})
SERIAL_FILE = 'tools/remote/serial_suites.txt'


class SelectionError(RuntimeError):
    pass


def serial_prefixes(repo) -> list[str]:
    """tools/remote/serial_suites.txt prefixes (xdist_plan.load_serial's format); none without a repo root."""
    root = getattr(repo, 'root', None)
    path = root / SERIAL_FILE if root is not None else None
    if path is None or not path.is_file():
        return []
    rows = (line.split('#', 1)[0].strip().strip('/') for line in path.read_text(encoding='utf-8').splitlines())
    return [row for row in rows if row]


def is_serial(path: str, serial: list[str]) -> bool:
    """xdist_plan.serial_reason's path rule: the path is, holds or sits under a serial suite."""
    path = path.strip('/')
    return any(path == s or path.startswith(s + '/') or s.startswith(path + '/') for s in serial)


def pack(repo, paths: list[str]) -> list[list[str]]:
    """Keep selected paths, separating conflicting imports and bounding commands.

    A serial suite never shares an invocation with others: remote_pytest runs a whole invocation without -n
    when any path in it is serial, so one gazebo path kept a dozen suites on one core (2026-10-28 turns)."""
    kept = [p for p in paths if not any(o != p and p.startswith(o.rstrip('/') + '/') for o in paths)]
    serial = serial_prefixes(repo)
    groups: list[tuple[list[str], dict[str, str], bool]] = []
    for path in kept:
        if len(path) + 1 > MAX_INVOCATION_CHARS:
            raise SelectionError(f'test path exceeds remote command budget: {path}')
        names = repo.test_import_names(path)
        alone = is_serial(path, serial)
        for members, seen, kind in groups:
            conflict = any(name in seen and seen[name] != source for name, source in names.items())
            if kind == alone and not conflict and sum(len(p) + 1 for p in members) + len(path) + 1 <= MAX_INVOCATION_CHARS:
                members.append(path)
                seen.update(names)
                break
        else:
            groups.append(([path], dict(names), alone))
    return [members for members, _, _ in groups]
