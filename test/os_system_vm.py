"""Private unprivileged QEMU/Ubuntu SYSTEM fixture; never constructs a product image."""
from __future__ import annotations

import functools
import fcntl
import hashlib
import http.server
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import socket
import stat
import subprocess
import threading
import time
from urllib.request import Request, urlopen
import uuid

PINS = Path(__file__).with_name("os_system_vm_inputs.json")
RANGE_BYTES = 8 * 1024**2
RANGE_THRESHOLD = 32 * 1024**2


def download(expected, target):
    target = Path(target)
    if target.exists() or target.is_symlink():
        raise ValueError("guest input destination already exists")
    partial = target.with_name(target.name + ".part")
    created = False
    try:
        with partial.open("xb") as output:
            created = True
            digest, total = hashlib.sha256(), 0
            ranged = expected["size_bytes"] >= RANGE_THRESHOLD and expected["url"].startswith(("https://", "http://"))
            step = RANGE_BYTES if ranged else expected["size_bytes"]
            # Bulk cloud transfers stalled after32MiB; bound each response but retain the whole-file SHA authority.
            for start in range(0, expected["size_bytes"], step):
                end = min(start + step, expected["size_bytes"]) - 1
                request = Request(expected["url"], headers={"Range": f"bytes={start}-{end}"}) if ranged else expected["url"]
                with urlopen(request, timeout=30) as source:
                    if ranged and (source.status != 206 or source.headers.get("Content-Range") != f"bytes {start}-{end}/{expected['size_bytes']}"):
                        raise ValueError("guest upstream returned a different byte range")
                    received = 0
                    while chunk := source.read(min(2 * 1024**2, end - start + 2 - received)):
                        received += len(chunk)
                        if received > end - start + 1:
                            raise ValueError("guest input exceeds its pinned size")
                        digest.update(chunk)
                        output.write(chunk)
                    if received != end - start + 1:
                        raise ValueError("guest input range ended early")
                    total += received
            if total != expected["size_bytes"] or digest.hexdigest() != expected["sha256"]:
                raise ValueError("guest input differs from its pinned bytes")
            output.flush()
            os.fsync(output.fileno())
        os.rename(partial, target)
    finally:
        if created:
            partial.unlink(missing_ok=True)


def cached_input(expected, target):
    """Only public pinned bytes are cached; mutable guests always receive a new copy."""
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache").absolute()
    cache = base / "rosy-os-system-inputs"
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = cache.stat()
    if cache.resolve() != cache or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("SYSTEM public cache is not privately owned")
    digest = expected["sha256"]
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("invalid SYSTEM input digest")
    cached = cache / (digest + ".bin")
    fd = os.open(cache / (digest + ".lock"), os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
            raise ValueError("unsafe SYSTEM cache lock")
        fcntl.flock(fd, fcntl.LOCK_EX)
        if not cached.exists() and not cached.is_symlink():
            download(expected, cached)
            cached.chmod(0o400)
        info = cached.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1
                or info.st_mode & 0o022 or info.st_size != expected["size_bytes"]):
            raise ValueError("unsafe SYSTEM cached input")
        digest = hashlib.sha256()
        with cached.open("rb") as source:
            while chunk := source.read(2 * 1024**2): digest.update(chunk)
            if digest.hexdigest() != expected["sha256"]:
                raise ValueError("SYSTEM cached input digest differs")
            source.seek(0)
            with Path(target).open("xb") as output:
                shutil.copyfileobj(source, output, 2 * 1024**2)
    finally:
        os.close(fd)


class _Seed(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_): pass


def _port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class Guest:
    def __init__(self, directory):
        self.directory = Path(directory).absolute()
        info = self.directory.stat()
        if (self.directory.resolve() != self.directory or self.directory == Path("/")
                or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022):
            raise ValueError("guest requires a private owned workspace")
        self.root = self.directory / "qemu-root"
        self.process = self.server = self.thread = self.stderr = None
        self.ssh_port = None

    def command(self, ssh_port, seed_port):
        d = self.directory
        return [str(self.root / "usr/bin/qemu-system-x86_64"), "-accel", "tcg", "-machine", "pc",
            "-cpu", "max", "-m", "2048", "-smp", "2", "-nodefaults", "-display", "none",
            "-monitor", "none", "-serial", "file:" + str(d / "guest-console.log"), "-no-reboot",
            "-L", str(self.root / "usr/share/qemu"), "-bios", str(self.root / "usr/share/seabios/bios-256k.bin"),
            "-kernel", str(d / "vmlinuz"), "-initrd", str(d / "initrd"),
            "-append", "root=/dev/vda1 rw console=ttyS0 panic=1",
            "-drive", f"file={d / 'guest.qcow2'},if=virtio,format=qcow2",
            "-drive", f"file={d / 'work.raw'},if=virtio,format=raw",
            "-netdev", f"user,id=network0,hostfwd=tcp:127.0.0.1:{ssh_port}-:22",
            "-device", "virtio-net-pci,netdev=network0,romfile=",
            "-smbios", f"type=1,serial=ds=nocloud-net;s=http://10.0.2.2:{seed_port}/"]

    def _prepare(self):
        if platform.machine() != "x86_64" or os.geteuid() == 0:
            raise ValueError("SYSTEM fixture requires an unprivileged native x86_64 Linux test host")
        pins = json.loads(PINS.read_bytes())
        self.root.mkdir(mode=0o700)
        for filename, size, sha in pins["debs"]:
            archive = self.directory / Path(filename).name
            cached_input(dict(url="https://archive.ubuntu.com/ubuntu/" + filename, size_bytes=size, sha256=sha), archive)
            subprocess.run(["dpkg-deb", "-x", str(archive), str(self.root)], check=True, capture_output=True, timeout=60)
        self.env = dict(os.environ, LD_LIBRARY_PATH=":".join(str(self.root / p) for p in
            ("usr/lib/x86_64-linux-gnu", "lib/x86_64-linux-gnu")),
            QEMU_MODULE_DIR=str(self.root / "usr/lib/x86_64-linux-gnu/qemu"))
        version = subprocess.run([str(self.root / "usr/bin/qemu-system-x86_64"), "--version"],
            env=self.env, capture_output=True, text=True, timeout=30)
        if version.returncode or "version 8.2.2" not in version.stdout:
            raise ValueError("private QEMU cannot run: " + version.stderr[-2000:])
        for local, (name, size, sha) in pins["cloud"].items():
            cached_input(dict(url=pins["cloud_base"] + name, size_bytes=size, sha256=sha), self.directory / local)
        with (self.directory / "work.raw").open("xb") as handle:
            handle.truncate(16 * 1024**3)
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(self.directory / "guest-key")],
                       check=True, capture_output=True, timeout=30)
        seed = self.directory / "seed"
        seed.mkdir(mode=0o700)
        public = (self.directory / "guest-key.pub").read_text().strip()
        (seed / "user-data").write_text("#cloud-config\ndisable_root: false\nssh_pwauth: false\nusers:\n"
            f"  - name: root\n    lock_passwd: true\n    ssh_authorized_keys:\n      - {public}\n")
        (seed / "meta-data").write_text(f"instance-id: rosy-system-{uuid.uuid4()}\nlocal-hostname: rosy-system-guest\n")
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Seed, directory=str(seed)))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.ssh_port = _port()
        self.stderr = (self.directory / "qemu-stderr.log").open("wb")
        self.process = subprocess.Popen(self.command(self.ssh_port, self.server.server_port), env=self.env,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=self.stderr, start_new_session=True)

    def _ssh(self, command, *, timeout=30, data=None):
        return subprocess.run(["ssh", "-p", str(self.ssh_port), "-i", str(self.directory / "guest-key"),
            "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-o", "ConnectTimeout=3", "-o", "LogLevel=ERROR",
            "-o", "StrictHostKeyChecking=accept-new", "-o", "UserKnownHostsFile=" + str(self.directory / "known-hosts"),
            "root@127.0.0.1", command], input=data, capture_output=True, timeout=timeout)

    def run(self, command, *, timeout=300, data=None):
        result = self._ssh(command, timeout=timeout, data=data)
        if result.returncode:
            raise ValueError("guest command failed: " + result.stderr.decode(errors="replace")[-3000:])
        return result.stdout.decode("utf-8", errors="replace")

    def __enter__(self):
        try:
            self._prepare()
            deadline = time.monotonic() + 480
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise ValueError("private QEMU exited: " + (self.directory / "qemu-stderr.log").read_text()[-2000:])
                try:
                    if self._ssh("true", timeout=5).returncode == 0:
                        return self
                except subprocess.TimeoutExpired:
                    pass
                time.sleep(2)
            raise ValueError("SYSTEM guest boot timeout: " + (self.directory / "guest-console.log").read_text(errors="replace")[-5000:])
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.process is not None and self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=10)
        if self.stderr is not None:
            self.stderr.close()
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=5)

    def __exit__(self, *_):
        self.close()
