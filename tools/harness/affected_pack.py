"""Pack affected pytest paths without cross-suite module-cache collisions."""

# Leave room for the remote runner's SSH command and options.
MAX_INVOCATION_CHARS = 3000
IGNORED_BASENAMES = frozenset({'__init__.py', 'conftest.py'})


class SelectionError(RuntimeError):
    pass


def pack(repo, paths: list[str]) -> list[list[str]]:
    """Keep selected paths, separating conflicting imports and bounding commands."""
    kept = [p for p in paths if not any(o != p and p.startswith(o.rstrip('/') + '/') for o in paths)]
    groups: list[tuple[list[str], dict[str, str]]] = []
    for path in kept:
        if len(path) + 1 > MAX_INVOCATION_CHARS:
            raise SelectionError(f'test path exceeds remote command budget: {path}')
        names = repo.test_import_names(path)
        for members, seen in groups:
            conflict = any(name in seen and seen[name] != source for name, source in names.items())
            if not conflict and sum(len(p) + 1 for p in members) + len(path) + 1 <= MAX_INVOCATION_CHARS:
                members.append(path)
                seen.update(names)
                break
        else:
            groups.append(([path], dict(names)))
    return [members for members, _ in groups]
