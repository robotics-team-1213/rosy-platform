"""D-553 addendum 3: which source changes a signed delta payload may carry."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("make_delta_release", ROOT / "tools" / "release" / "make_delta_release.py")
tool = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(tool)

OLD = {"src/pkg/pkg/mod.py": b"old mod\n", "src/pkg/pkg/__init__.py": b"",
       "src/other/other/__init__.py": b"", "src/pkg/config/x.yaml": b"k: 1\n",
       "src/pkg/src/node.cpp": b"int main(){}\n", "docs/a.md": b"a\n", "src/pkg/gen.txt": b"in\n"}
BASE = {"install/lib/python3.12/site-packages/pkg/mod.py": OLD["src/pkg/pkg/mod.py"],
        "install/lib/python3.12/site-packages/pkg/__init__.py": b"",
        "install/lib/python3.12/site-packages/other/__init__.py": b"",
        "install/share/pkg/config/x.yaml": OLD["src/pkg/config/x.yaml"],
        "install/share/pkg/gen.txt": b"transformed\n"}
BASE_FILES = {path: hashlib.sha256(data).hexdigest() for path, data in BASE.items()}


def plan(changes, new=None, extra=(), twins=None):
    new = new or {}
    blob = lambda side, path: OLD[path] if side == "old" else new.get(path, b"changed\n")  # noqa: E731
    counts = twins or (lambda path: 2 if path.endswith("__init__.py") else 1)
    return tool.plan_delta(BASE_FILES, changes, blob, list(extra), counts)


def test_a_changed_python_module_and_config_map_to_their_verbatim_copies():
    replace, ignored = plan([("M", "src/pkg/pkg/mod.py"), ("M", "src/pkg/config/x.yaml"), ("M", "docs/a.md")])
    assert replace == {"install/lib/python3.12/site-packages/pkg/mod.py": b"changed\n",
                       "install/share/pkg/config/x.yaml": b"changed\n"}
    assert ignored == ["docs/a.md"]


def test_an_empty_init_only_replaces_the_copy_with_the_same_parent():
    replace, _ = plan([("M", "src/pkg/pkg/__init__.py")])
    assert list(replace) == ["install/lib/python3.12/site-packages/pkg/__init__.py"]


@pytest.mark.parametrize("change, reason", [
    (("M", "src/pkg/src/node.cpp"), "build input"),
    (("M", "src/pkg/gen.txt"), "no verbatim copy"),
    (("A", "src/pkg/pkg/new.py"), "added"),
    (("D", "src/pkg/pkg/mod.py"), "deleted"),
])
def test_anything_else_needs_a_full_build(change, reason):
    with pytest.raises(tool.DeltaError, match=reason):
        plan([("M", "src/pkg/pkg/mod.py"), change])


def test_not_shipped_prefixes_are_ignored_and_an_empty_delta_is_refused():
    _, ignored = plan([("M", "src/pkg/pkg/mod.py"), ("A", "deploy/site/x.py")], extra=["deploy/site"])
    assert ignored == ["deploy/site/x.py"]
    with pytest.raises(tool.DeltaError, match="nothing shipped"):
        plan([("M", "docs/a.md")])


def test_push_preflight_accepts_a_signed_delta_and_refuses_a_tampered_file(tmp_path):
    import subprocess
    import signing
    private, public = tmp_path / "k.pem", tmp_path / "k.pub.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(private)], check=True, capture_output=True)
    subprocess.run(["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)], check=True, capture_output=True)
    full = {"manifest.json": b"{}\n", "install/a.py": b"new\n", "install/b.py": b"unchanged, not in the delta\n"}
    sums = "".join(f"{hashlib.sha256(d).hexdigest()}  {p}\n" for p, d in sorted(full.items())).encode()
    delta = tmp_path / "delta"
    (delta / "install").mkdir(parents=True)
    for path in ("manifest.json", "install/a.py"):
        (delta / path).write_bytes(full[path])
    (delta / "SHA256SUMS").write_bytes(sums)
    (delta / "SHA256SUMS.sig").write_text(signing.sign_checksums(sums, private))
    (delta / signing.DELTA_MARKER).write_text("2026.10.01-001\n" + "a" * 64 + "\n")

    assert signing.verify_delta_files(delta, public) == []
    assert signing.verify_release_files(delta, public)  # the full check needs the base files
    (delta / "install" / "a.py").write_bytes(b"tampered\n")
    assert [r.code for r in signing.verify_delta_files(delta, public)] == ["CHECKSUM_MISMATCH"]
