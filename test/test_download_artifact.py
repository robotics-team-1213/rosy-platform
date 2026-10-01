"""tools/release/download_artifact.py against a local HTTP range server (no network)."""

from __future__ import annotations

import importlib.util
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import threading
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("download_artifact", ROOT / "tools" / "release" / "download_artifact.py")
tool = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(tool)

TOKEN = "fixture-token-must-not-leak"
SIGNATURE = "sig=fixture-signed-secret"
REPO = "owner/rosy-os"


def _zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as bundle:
        for name, data in entries.items():
            bundle.writestr(name, data)
    return buffer.getvalue()


class Server:
    def __init__(self, blob: bytes, *, api_size: int | None = None, fail_first: int = 0, honour_range: bool = True,
                 short_first: int = 0):
        self.short_first = short_first
        self.blob = blob
        self.api_size = len(blob) if api_size is None else api_size
        self.fail_first = fail_first
        self.honour_range = honour_range
        self.signed_urls = 0
        self.blob_bytes = 0
        self.blob_auth_headers = 0
        self.lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _json(self, payload):
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802
                artifact = {"id": 7, "name": "rosy-os-image", "size_in_bytes": outer.api_size, "expired": False}
                if self.path.startswith("/repos/"):
                    if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                        self.send_error(401)
                        return
                    if self.path == f"/repos/{REPO}/actions/runs/99/artifacts?name=rosy-os-image&per_page=100":
                        self._json({"artifacts": [artifact, {**artifact, "id": 8, "name": "other"}]})
                    elif self.path == f"/repos/{REPO}/actions/artifacts/7":
                        self._json(artifact)
                    elif self.path == f"/repos/{REPO}/actions/artifacts/7/zip":
                        with outer.lock:
                            outer.signed_urls += 1
                        self.send_response(302)
                        self.send_header("Location", f"http://127.0.0.1:{outer.port}/blob?{SIGNATURE}")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                    else:
                        self.send_error(404)
                    return
                if not self.path.startswith("/blob?" + SIGNATURE):
                    self.send_error(403)
                    return
                with outer.lock:
                    if self.headers.get("Authorization"):
                        outer.blob_auth_headers += 1
                    if outer.fail_first > 0:
                        outer.fail_first -= 1
                        self.send_error(500)
                        return
                match = re.fullmatch(r"bytes=(\d+)-(\d+)", self.headers.get("Range", ""))
                if not outer.honour_range or not match:
                    body = outer.blob
                    self.send_response(200)
                else:
                    start, end = int(match.group(1)), int(match.group(2))
                    if start >= len(outer.blob):
                        self.send_error(416)
                        return
                    end = min(end, len(outer.blob) - 1)
                    body = outer.blob[start:end + 1]
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{end}/{len(outer.blob)}")
                with outer.lock:
                    outer.blob_bytes += len(body)
                    cut = outer.short_first > 0
                    if cut:
                        outer.short_first -= 1
                self.send_header("Content-Length", str(len(body)))
                if cut:  # promise the whole range, send half, drop the connection
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(body[:len(body) // 2])
                    self.close_connection = True
                    return
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", TOKEN)
    monkeypatch.setattr(tool, "REQUEST_BYTES", 4096)
    monkeypatch.setattr(tool.time, "sleep", lambda _s: None)


def _main(server, *args):
    return tool.main(["--repo", REPO, "--api-base", f"http://127.0.0.1:{server.port}",
                      "--progress-seconds", "0.01", *map(str, args)])


BLOB = _zip({"release/rosy-os.img.xz": bytes(range(256)) * 300, "release/SHA256SUMS": b"abc  rosy-os.img.xz\n"})


def test_run_and_name_download_in_parallel_ranges_with_progress_and_no_secrets(tmp_path, capsys):
    out = tmp_path / "artifact.zip"
    with Server(BLOB) as server:
        assert _main(server, "--run", 99, "--name", "rosy-os-image", "--out", out, "--workers", 4) == 0
        assert server.blob_auth_headers == 0  # the token never goes to the signed-URL host
    assert out.read_bytes() == BLOB
    assert not Path(str(out) + ".parts").exists()
    printed = capsys.readouterr()
    text = printed.out + printed.err
    assert "in 4 parts" in text and "MB/s" in text and "eta" in text and "complete:" in text
    assert TOKEN not in text and SIGNATURE not in text and "/blob" not in text


def test_an_interrupted_download_resumes_its_parts(tmp_path):
    out = tmp_path / "artifact.zip"
    with Server(BLOB) as server:
        downloader = tool.Downloader(tool.GitHub(f"http://127.0.0.1:{server.port}", REPO, TOKEN),
                                     {"id": 7, "size_in_bytes": len(BLOB)}, out, 2, 60)
        ranges = downloader._prepare_parts()
        first, last = ranges[0]
        downloader._part(0).write_bytes(BLOB[first:last + 1])  # part 0 already done
        downloader._part(1).write_bytes(BLOB[ranges[1][0]:ranges[1][0] + 100])  # part 1 started
        downloader.run()
        assert server.blob_bytes == len(BLOB) - (last + 1) - 100
    assert out.read_bytes() == BLOB


def test_parts_of_another_artifact_are_not_resumed(tmp_path, capsys):
    out = tmp_path / "artifact.zip"
    parts = Path(str(out) + ".parts")
    parts.mkdir()
    (parts / "meta.json").write_text(json.dumps({"artifact_id": 5, "size": 10, "workers": 2}))
    with Server(BLOB) as server:
        assert _main(server, "--artifact-id", 7, "--out", out, "--workers", 2) == 1
    assert "parts of another download" in capsys.readouterr().err


def test_server_errors_are_retried_with_a_fresh_signed_url(tmp_path):
    out = tmp_path / "artifact.zip"
    with Server(BLOB, fail_first=3) as server:
        assert _main(server, "--artifact-id", 7, "--out", out, "--workers", 1) == 0
        assert server.signed_urls >= 2
    assert out.read_bytes() == BLOB


def test_a_server_that_ignores_range_is_refused(tmp_path, capsys):
    with Server(BLOB, honour_range=False) as server:
        assert _main(server, "--artifact-id", 7, "--out", tmp_path / "a.zip", "--workers", 2) == 1
    assert "did not honour the byte range" in capsys.readouterr().err


def test_a_size_that_disagrees_with_the_api_never_yields_a_file(tmp_path, capsys):
    out = tmp_path / "a.zip"
    with Server(BLOB, api_size=len(BLOB) + 10) as server:
        assert _main(server, "--artifact-id", 7, "--out", out, "--workers", 2) == 1
    assert not out.exists()


def test_assembly_checks_the_api_size(tmp_path, monkeypatch):
    # Defence in depth: parts that do not add up to the API size never become the output.
    real = tool.Downloader._ranges
    monkeypatch.setattr(tool.Downloader, "_ranges", lambda self: [(a, b - (b == self.size - 1)) for a, b in real(self)])
    out = tmp_path / "a.zip"
    with Server(BLOB) as server:
        with pytest.raises(tool.DownloadError, match="assembled size"):
            tool.Downloader(tool.GitHub(f"http://127.0.0.1:{server.port}", REPO, TOKEN),
                            {"id": 7, "size_in_bytes": len(BLOB)}, out, 2, 60).run()
    assert not out.exists()


def test_extract_validates_and_unpacks(tmp_path, capsys):
    out = tmp_path / "a.zip"
    with Server(BLOB) as server:
        assert _main(server, "--artifact-id", 7, "--out", out, "--extract", tmp_path / "rel") == 0
    assert (tmp_path / "rel" / "release" / "SHA256SUMS").read_bytes() == b"abc  rosy-os.img.xz\n"


@pytest.mark.parametrize("name", ["../evil.txt", "release/../../evil.txt", "/abs/evil.txt", "C:/evil.txt",
                                  "..\\evil.txt"])
def test_extract_refuses_path_traversal(tmp_path, name):
    archive = tmp_path / "bad.zip"
    archive.write_bytes(_zip({"ok.txt": b"ok", name: b"x"}))
    with pytest.raises(tool.DownloadError, match="outside the destination"):
        tool.safe_extract(archive, tmp_path / "dest")
    assert not (tmp_path / "dest").exists()
    assert not (tmp_path / "evil.txt").exists()


def test_extract_refuses_a_corrupt_entry(tmp_path):
    data = bytearray(_zip({"a.bin": b"A" * 1000}))
    data[data.index(b"A" * 100) + 10] ^= 0xFF
    archive = tmp_path / "bad.zip"
    archive.write_bytes(bytes(data))
    with pytest.raises(tool.DownloadError, match="CRC"):
        tool.safe_extract(archive, tmp_path / "dest")
    assert not (tmp_path / "dest").exists()


# Review (MEDIUM): a connection cut mid-body raises http.client.IncompleteRead,
# which is not an OSError; it must be retried, not end the run.
def test_a_short_body_is_retried(tmp_path):
    out = tmp_path / "a.zip"
    with Server(BLOB, short_first=2) as server:
        assert _main(server, "--artifact-id", 7, "--out", out, "--workers", 1) == 0
        assert server.short_first == 0
    assert out.read_bytes() == BLOB


# Review (LOW): an output already on disk is checked like a fresh download.
def test_an_existing_output_is_checked_not_trusted_on_size(tmp_path, capsys):
    out = tmp_path / "a.zip"
    out.write_bytes(b"\0" * len(BLOB))  # the right size, not the artifact
    with Server(BLOB) as server:
        assert _main(server, "--artifact-id", 7, "--out", out) == 1
        assert server.blob_bytes == 0
    assert "fails its check" in capsys.readouterr().err
    assert out.read_bytes() == b"\0" * len(BLOB)  # never silently replaced


def test_a_fresh_download_gets_the_same_check(tmp_path, capsys):
    corrupt = bytearray(BLOB)
    corrupt[corrupt.index(bytes(range(256))) + 7] ^= 0xFF  # right size, a failing CRC
    out = tmp_path / "a.zip"
    with Server(bytes(corrupt)) as server:
        assert _main(server, "--artifact-id", 7, "--out", out, "--workers", 2) == 1
    assert "fails its CRC check" in capsys.readouterr().err
    assert not out.exists()


def test_a_valid_existing_output_is_reused(tmp_path, capsys):
    out = tmp_path / "a.zip"
    out.write_bytes(BLOB)
    with Server(BLOB) as server:
        assert _main(server, "--artifact-id", 7, "--out", out) == 0
        assert server.blob_bytes == 0
    assert "already complete (size and zip CRC checked)" in capsys.readouterr().out


# Review (LOW): a symlink entry is refused explicitly, whatever its name.
def test_extract_refuses_a_symlink_entry(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        bundle.writestr("ok.txt", b"ok")
        link = zipfile.ZipInfo("release/link")
        link.external_attr = (0o120777 << 16)
        bundle.writestr(link, "../../outside")
    archive = tmp_path / "link.zip"
    archive.write_bytes(buffer.getvalue())
    with pytest.raises(tool.DownloadError, match="symlink"):
        tool.safe_extract(archive, tmp_path / "dest")
    assert not (tmp_path / "dest").exists()
