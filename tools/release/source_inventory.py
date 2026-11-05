"""Read complete, bounded GitHub trees when the compare file list is truncated.

The caller retains the ancestry and repository checks. Candidate code and URLs
are never executed; all requests use exact object IDs in the trusted API client.
"""
import re


SHA = re.compile(r"[0-9a-f]{40}")
MAX_ENTRIES = 100_000
_MODES = {"tree": {"040000"}, "blob": {"100644", "100755", "120000"},
          "commit": {"160000"}}


def _valid_path(path):
    if (not isinstance(path, str) or not path or path.startswith("/")
            or "\\" in path or re.match(r"[A-Za-z]:", path)
            or any(ord(c) < 32 or ord(c) == 127 for c in path)
            or any(part in ("", ".", "..") for part in path.split("/"))):
        return False
    try:
        return len(path.encode("utf-8")) <= 4096
    except UnicodeEncodeError:
        return False


def _inventory(api, revision):
    commit = api(f"git/commits/{revision}")
    if not isinstance(commit, dict) or commit.get("sha") != revision:
        return None
    tree = commit.get("tree")
    tree_sha = tree.get("sha") if isinstance(tree, dict) else None
    if not isinstance(tree_sha, str) or not SHA.fullmatch(tree_sha):
        return None
    reply = api(f"git/trees/{tree_sha}?recursive=1")
    if (not isinstance(reply, dict) or reply.get("sha") != tree_sha
            or reply.get("truncated") is not False
            or not isinstance(reply.get("tree"), list)
            or len(reply["tree"]) > MAX_ENTRIES):
        return None
    entries = {}
    for item in reply["tree"]:
        if not isinstance(item, dict):
            return None
        path, sha, kind, mode = (item.get(k) for k in ("path", "sha", "type", "mode"))
        if (not _valid_path(path) or path in entries or not isinstance(sha, str)
                or not SHA.fullmatch(sha) or not isinstance(kind, str) or not isinstance(mode, str)
                or mode not in _MODES.get(kind, ())):
            return None
        entries[path] = {"sha": sha, "type": kind, "mode": mode}
    for path in entries:
        parent = path.rpartition("/")[0]
        if parent and (parent not in entries or entries[parent]["type"] != "tree"):
            return None
    return entries


def _regular(entry):
    return entry["type"] == "blob" and entry["mode"] in {"100644", "100755"}


def changes(api, base, head):
    """Return sorted filename/status/sha records, or None for incomplete evidence.

    Mode/type changes and special entries remain visible as unsupported so a
    caller may classify their paths but must not turn them into a byte-only delta.
    Transport failures propagate rather than masquerading as an empty inventory.
    """
    if any(not isinstance(sha, str) or not SHA.fullmatch(sha) for sha in (base, head)):
        return None
    old = _inventory(api, base)
    if old is None:
        return None
    new = _inventory(api, head)
    if new is None:
        return None
    result = []
    for path in sorted(old.keys() | new.keys()):
        before, after = old.get(path), new.get(path)
        if before == after:
            continue
        if all(item is None or item["type"] == "tree" for item in (before, after)):
            continue  # Directory hashes are represented by their changed leaves.
        if before is None:
            status = "added" if _regular(after) else "unsupported"
        elif after is None:
            status = "removed" if _regular(before) else "unsupported"
        elif (_regular(before) and _regular(after)
              and before["mode"] == after["mode"]):
            status = "modified"
        else:
            status = "unsupported"
        result.append({"filename": path, "status": status, "sha": (after or before)["sha"]})
    return result
