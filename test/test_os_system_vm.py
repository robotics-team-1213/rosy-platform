"""Opt-in disposable guest verification; never a release-image builder or a host installer."""
import hashlib
import importlib
import os
from pathlib import Path

import pytest


def module():
    return importlib.import_module("os_system_vm")


def test_guest_download_rejects_hash_or_size_before_publishing(tmp_path):
    m = module()
    source = tmp_path / "upstream"
    source.write_bytes(b"known bytes")
    expected = dict(url=source.as_uri(), size_bytes=11, sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    m.download(expected, tmp_path / "verified")
    assert (tmp_path / "verified").read_bytes() == source.read_bytes()
    for field, value in (("size_bytes", 10), ("sha256", "0" * 64)):
        with pytest.raises(ValueError): m.download({**expected, field: value}, tmp_path / field)
        assert not (tmp_path / field).exists()


def test_cached_public_inputs_are_reverified_and_copied_independently(tmp_path, monkeypatch):
    m = module()
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    source = tmp_path / "upstream"
    source.write_bytes(b"known bytes")
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    expected = dict(url=source.as_uri(), size_bytes=11, sha256=sha)
    m.cached_input(expected, tmp_path / "first")
    (tmp_path / "first").write_bytes(b"guest writes")
    monkeypatch.setattr(m, "urlopen", lambda *a, **k: pytest.fail("verified cache was downloaded again"))
    m.cached_input(expected, tmp_path / "second")
    assert (tmp_path / "second").read_bytes() == b"known bytes"
    cached = tmp_path / "cache/rosy-os-system-inputs" / (sha + ".bin")
    cached.chmod(0o600)
    cached.write_bytes(b"bad cache!!")
    with pytest.raises(ValueError): m.cached_input(expected, tmp_path / "third")
    assert not (tmp_path / "third").exists()


def test_qemu_command_has_only_owned_images_and_loopback_ssh(tmp_path):
    m = module()
    vm = m.Guest(tmp_path)
    argv = vm.command(22022, 22023)
    assert "-accel" in argv and argv[argv.index("-accel") + 1] == "tcg"
    assert "hostfwd=tcp:127.0.0.1:22022-:22" in " ".join(argv)
    assert "-enable-kvm" not in argv
    assert all(value.startswith("file=" + str(tmp_path) + "/") for key, value in zip(argv, argv[1:]) if key == "-drive")
    assert all(str(tmp_path) in value for key, value in zip(argv, argv[1:]) if key in {"-kernel", "-initrd", "-bios"})


@pytest.mark.parametrize("wrong_range", [False, True])
def test_large_guest_input_uses_exact_bounded_http_ranges(tmp_path, monkeypatch, wrong_range):
    import http.server
    import re
    import threading
    m = module()
    monkeypatch.setattr(m, "RANGE_BYTES", 8192, raising=False)
    monkeypatch.setattr(m, "RANGE_THRESHOLD", 8192, raising=False)
    data, requests = b"bounded upstream range data" * 1000, []
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_GET(self):
            match = re.fullmatch(r"bytes=(\d+)-(\d+)", self.headers.get("Range", ""))
            if not match:
                self.send_error(400)
                return
            start, end = map(int, match.groups())
            requests.append((start, end))
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start + int(wrong_range)}-{end}/{len(data)}")
            self.send_header("Content-Length", str(end - start + 1))
            self.end_headers()
            self.wfile.write(data[start:end + 1])
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    expected = dict(url=f"http://127.0.0.1:{server.server_port}/fixture", size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    try:
        if wrong_range:
            with pytest.raises(ValueError): m.download(expected, tmp_path / "image")
            assert not (tmp_path / "image").exists()
        else:
            m.download(expected, tmp_path / "image")
            assert (tmp_path / "image").read_bytes() == data
            assert requests == [(start, min(start + 8191, len(data) - 1)) for start in range(0, len(data), 8192)]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.skipif(os.environ.get("ROSY_RUN_OS_SYSTEM_TESTS") != "1", reason="explicit disposable SYSTEM guest opt-in")
def test_actual_guest_runs_pid1_without_host_privileges(tmp_path):
    m = module()
    with m.Guest(tmp_path) as guest:
        facts = guest.run("cat /proc/1/comm; systemctl --version | head -1; id -u; uname -m")
        assert facts.splitlines()[0] == "systemd"
        assert "systemd 255" in facts and "\n0\n" in facts and "x86_64" in facts
        # These block devices are guest-local virtual devices, never host hardware.
        assert "virtio" in guest.run("readlink -f /sys/class/block/vdb/device")
