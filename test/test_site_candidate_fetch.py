"""Host fetch script for CI-built site candidates (D-437), run against a fake curl."""

from __future__ import annotations

import hashlib
import io
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "site" / "fetch_candidate.sh"
COMMIT = "c" * 40
TAG = f"site-{COMMIT[:12]}"


def _bash() -> str | None:
    if sys.platform == "win32":
        git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
        return str(git_bash) if git_bash.is_file() else None
    return shutil.which("bash")


BASH = _bash()
pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash (Git Bash on Windows)")


def _posix(path: Path) -> str:
    text = path.as_posix()
    if sys.platform == "win32" and len(text) > 1 and text[1] == ":":
        text = f"/{text[0].lower()}{text[2:]}"  # Git Bash form; "X:" would split PATH
    return text


def _release(assets: Path, *, members: dict[str, bytes] | None = None, signed: bool = True,
             extra: str | None = None, special: tuple[tarfile.TarInfo, ...] = ()) -> None:
    assets.mkdir()
    manifest = b'{"source_commit": "' + COMMIT.encode() + b'"}\n'
    members = members or {
        f"{COMMIT}/release.json": manifest,
        f"{COMMIT}/images.tar": b"image archive " * 1000,
        f"{COMMIT}/deploy/site/compose.yaml": b"services: {}\n",
    }
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.GNU_FORMAT) as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        for info in special:
            archive.addfile(info)
    blob = buffer.getvalue()
    half = len(blob) // 2
    names = []
    for index, chunk in enumerate((blob[:half], blob[half:])):
        name = f"rosy-site-candidate-{COMMIT}.tar.part{index:02d}"
        (assets / name).write_bytes(chunk)
        names.append(name)
    (assets / "release.json").write_bytes(manifest)
    names.insert(0, "release.json")
    if extra:
        (assets / extra).write_bytes(b"x")
        names.append(extra)
    (assets / "SHA256SUMS").write_text("".join(
        f"{hashlib.sha256((assets / name).read_bytes()).hexdigest()}  {name}\n"
        for name in names), encoding="utf-8", newline="\n")
    if signed:
        (assets / "release.json.sig").write_text('{"signature_version":1}\n', encoding="utf-8")


def _run(tmp_path: Path, assets: Path) -> subprocess.CompletedProcess:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    curl = fake_bin / "curl"
    # Fake curl: serve the URL's basename from the assets folder, fail on 404.
    curl.write_text(
        "#!/usr/bin/env bash\n"
        "out=; for a in \"$@\"; do case \"$prev\" in --output) out=$a;; esac; prev=$a; done\n"
        "url=${!#}\n"
        f"case \"$url\" in https://github.com/example/rosy/releases/download/{TAG}/*) ;; "
        "*) exit 22;; esac\n"
        f"src='{_posix(assets)}'/\"${{url##*/}}\"\n"
        "[ -f \"$src\" ] || exit 22\n"
        "cp \"$src\" \"$out\"\n",
        encoding="utf-8", newline="\n")
    curl.chmod(0o755)
    python3 = fake_bin / "python3"
    python3.write_text(
        f"#!/usr/bin/env bash\nexec '{_posix(Path(sys.executable))}' \"$@\"\n",
        encoding="utf-8", newline="\n")
    python3.chmod(0o755)
    return subprocess.run(
        [BASH, "-c", f'PATH="{_posix(fake_bin)}:$PATH" exec bash "$0" "$@"',
         _posix(SCRIPT), "--repo", "example/rosy", "--commit", COMMIT,
         "--staging", _posix(tmp_path / "staging")],
        capture_output=True, text=True, timeout=120,
    )


def test_fetch_reassembles_parts_and_adds_the_signature(tmp_path):
    assets = tmp_path / "assets"
    _release(assets)

    result = _run(tmp_path, assets)

    assert result.returncode == 0, result.stderr
    candidate = tmp_path / "staging" / TAG / "candidate" / COMMIT
    assert (candidate / "images.tar").read_bytes() == b"image archive " * 1000
    assert (candidate / "release.json.sig").is_file()
    assert (candidate / "release.json").read_bytes() == (assets / "release.json").read_bytes()
    assert not list((tmp_path / "staging" / TAG / "download").glob("*.part*"))
    assert "--signature-only" in result.stdout
    out = result.stdout
    assert out.index("--signature-only") < out.index("docker image load") < out.index(
        "systemctl restart")


def test_fetch_refuses_an_unsigned_release(tmp_path):
    assets = tmp_path / "assets"
    _release(assets, signed=False)

    result = _run(tmp_path, assets)

    assert result.returncode != 0
    assert "UNSIGNED" in result.stderr
    assert not (tmp_path / "staging" / TAG / "candidate" / COMMIT).exists()


def test_fetch_refuses_unexpected_assets_and_members(tmp_path):
    assets = tmp_path / "assets"
    _release(assets, extra="evil.sh")
    result = _run(tmp_path, assets)
    assert result.returncode != 0
    assert "unexpected asset" in result.stderr

    other = tmp_path / "other"
    other.mkdir()
    assets = other / "assets"
    _release(assets, members={"elsewhere/file": b"x", f"{COMMIT}/release.json": b"{}"})
    result = _run(other, assets)
    assert result.returncode != 0
    assert "unexpected archive member" in result.stderr
    assert not (other / "staging" / TAG / "candidate" / "elsewhere").exists()


def test_fetch_refuses_a_tampered_part(tmp_path):
    assets = tmp_path / "assets"
    _release(assets)
    part = assets / f"rosy-site-candidate-{COMMIT}.tar.part01"
    part.write_bytes(part.read_bytes()[:-1] + b"!")

    result = _run(tmp_path, assets)

    assert result.returncode != 0
    assert not (tmp_path / "staging" / TAG / "candidate" / COMMIT).exists()


def _link(name: str, kind: bytes, target: str) -> tarfile.TarInfo:
    info = tarfile.TarInfo(f"{COMMIT}/{name}")
    info.type = kind
    info.linkname = target
    return info


def test_fetch_refuses_symlinks_hardlinks_and_devices_before_extracting(tmp_path):
    fifo = tarfile.TarInfo(f"{COMMIT}/pipe")
    fifo.type = tarfile.FIFOTYPE
    cases = {
        "symlink": _link("deploy/site/compose.yaml.link", tarfile.SYMTYPE, "/etc/shadow"),
        "hardlink": _link("evil", tarfile.LNKTYPE, f"{COMMIT}/release.json"),
        "fifo": fifo,
    }
    for label, member in cases.items():
        case = tmp_path / label
        case.mkdir()
        _release(case / "assets", special=(member,))

        result = _run(case, case / "assets")

        assert result.returncode != 0, label
        assert "refusing non-regular archive member" in result.stderr, label
        assert not (case / "staging" / TAG / "candidate" / COMMIT).exists(), label


def test_fetch_refuses_absolute_and_parent_paths(tmp_path):
    for label, name in {"absolute": "/etc/rosy-evil", "parent": f"{COMMIT}/../escape"}.items():
        case = tmp_path / label
        case.mkdir()
        _release(case / "assets", members={name: b"x", f"{COMMIT}/release.json": b"{}"})

        result = _run(case, case / "assets")

        assert result.returncode != 0, label
        assert "unexpected archive member" in result.stderr, label
        assert not (case / "staging" / TAG / "candidate" / COMMIT).exists(), label
        assert not (case / "staging" / TAG / "escape").exists(), label
