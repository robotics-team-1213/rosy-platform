"""Owned QEMU/Ubuntu tools guest for verification and offline preparation, never a native release builder."""
from __future__ import annotations

import functools
import base64
try:
    import fcntl
except ImportError:
    fcntl = None
import hashlib
import http.server
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import socket
import stat
import subprocess
import tarfile
import tempfile
import threading
import time
from urllib.request import Request, urlopen
import uuid

PINS = Path(__file__).with_name("os_system_vm_inputs.json")
RANGE_BYTES = 8 * 1024**2
RANGE_THRESHOLD = 32 * 1024**2
# Extractor components independently recovered from maintainer MSI 7z2605-x64.msi.
WINDOWS_7ZIP = {
    '7z.exe': (577536, '94205cfc054dd3bbeb978905bc619a65b3f04e9e73bb2717841110b6f46d962e'),
    '7z.dll': (1908736, '78bf6b668d75801e3aa180b4ccb16e6d8395fba80dec8a065055bb6f8dfabb82'),
}
WINDOWS_QEMU_PACKAGE = (206615928,
    '5bcf9eed634e8575a37b74f445af41a2fe4106da512d0c30c368301d4c105037'
    'fdfab40a5287367a28a957624cddebbc8c07e16c88ab6634f554cdf3d16bf543')
SOURCE_PATHS = ('deploy/robot/pinky_pro', 'deploy/hosts/common', 'contracts/foundation', 'tools/harness',
                'tools/release/os_tools_vm.py', 'tools/release/os_system_vm_inputs.json',
                'tools/release/external_os_signing.py', 'test',
                'shared/web/tokens.css', 'shared/web/components.css')


def pid1_start(raw, unit, boot_id, earliest_us):
    boot = uuid.UUID(boot_id).hex
    for line in raw.splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if not isinstance(event, dict):
            raise ValueError("journal entry is not an object")
        # systemd v255 sd-messages.h: SD_MESSAGE_UNIT_STARTING.
        if (event.get("UNIT") == unit and event.get("_PID") == "1"
                and event.get("_BOOT_ID") == boot
                and event.get("MESSAGE_ID") == "7d4958e842da4a758f6c1cdc7b36dcc5"):
            stamp = event.get("__MONOTONIC_TIMESTAMP", "")
            if isinstance(stamp, str) and stamp.isdecimal() and int(stamp) >= earliest_us:
                return event
    raise ValueError("no matching PID1 unit-start event after the boot deadline")


def committed_archive(source: Path, revision: str) -> bytes:
    """Operator preparation never includes uncommitted, ignored or untracked files."""
    if not isinstance(revision, str) or not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('operator source requires an exact commit revision')
    command = ['git', '-C', str(Path(source).absolute())]
    kind = subprocess.run([*command, 'cat-file', '-t', revision], check=True,
                          capture_output=True, timeout=30).stdout.strip()
    if kind != b'commit':
        raise ValueError('operator source revision is not a commit')
    queries = ''.join(revision + ':' + name + '\n' for name in SOURCE_PATHS).encode('utf-8')
    kinds = subprocess.run([*command, 'cat-file', '--batch-check=%(objecttype)'], input=queries,
                           check=True, capture_output=True, timeout=30).stdout.splitlines()
    if len(kinds) != len(SOURCE_PATHS):
        raise ValueError('operator source path lookup differs')
    paths = [name for name, kind in zip(SOURCE_PATHS, kinds) if kind in (b'tree', b'blob')]
    top = subprocess.run([*command, 'ls-tree', '-z', '--name-only', revision],
                         check=True, capture_output=True, timeout=30).stdout.split(b'\0')
    paths.extend(name.decode('utf-8') for name in top if name.endswith(b'.yaml') and b'/' not in name)
    if not paths:
        raise ValueError('operator source has no allowlisted inputs')
    with tempfile.TemporaryFile() as output:
        subprocess.run([*command, '-c', 'tar.umask=0022', 'archive', '--format=tar.gz', revision, '--', *paths],
                       stdout=output, stderr=subprocess.PIPE, check=True, timeout=120)
        output.seek(0)
        raw = output.read(128 * 1024**2 + 1)
    if len(raw) > 128 * 1024**2:
        raise ValueError('operator source handoff exceeds its expected size')
    return raw


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
    if fcntl is None:
        raise ValueError('shared SYSTEM cache requires POSIX file locking')
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
    binary = "qemu-system-x86_64"
    work_bytes = 16 * 1024**3

    def pins(self):
        return json.loads(PINS.read_bytes())

    def prepare_boot(self):
        pass

    def __init__(self, directory):
        self.directory = Path(directory).absolute()
        if (self.directory.resolve() != self.directory or self.directory == Path(self.directory.anchor)
                or any(c in str(self.directory) for c in ',\r\n\0')):
            raise ValueError('guest requires a private owned workspace')
        self._check_workspace()
        self.root = self.directory / "qemu-root"
        self.process = self.server = self.thread = self.stderr = None
        self.ssh_port = None
        self.instance_id = "rosy-system-" + str(uuid.uuid4())

    def _check_workspace(self):
        info = self.directory.stat()
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022:
            raise ValueError("guest requires a private owned workspace")

    def _qemu_files(self):
        return (self.root / 'usr/bin' / self.binary, self.root / 'usr/share/qemu',
                self.root / 'usr/share/seabios/bios-256k.bin')

    def _process_options(self, *, session=False):
        return dict(start_new_session=True) if session else {}

    def command(self, ssh_port, seed_port):
        d = self.directory
        binary, share, bios = self._qemu_files()
        return [str(binary), "-accel", "tcg", "-machine", "pc",
            "-cpu", "max", "-m", "2048", "-smp", "2", "-nodefaults", "-display", "none",
            "-monitor", "none", "-serial", "file:" + str(d / "guest-console.log"), "-no-reboot",
            "-L", str(share), "-bios", str(bios),
            "-kernel", str(d / "vmlinuz"), "-initrd", str(d / "initrd"),
            "-append", "root=/dev/vda1 rw console=ttyS0 panic=1",
            "-drive", f"file={d / 'guest.qcow2'},if=virtio,format=qcow2",
            "-drive", f"file={d / 'work.raw'},if=virtio,format=raw",
            "-netdev", f"user,id=network0,hostfwd=tcp:127.0.0.1:{ssh_port}-:22",
            "-device", "virtio-net-pci,netdev=network0,romfile=",
            "-smbios", f"type=1,serial=ds=nocloud-net;s=http://10.0.2.2:{seed_port}/"]

    def _prepare_tools(self):
        if platform.machine() != "x86_64" or os.geteuid() == 0:
            raise ValueError("SYSTEM fixture requires an unprivileged native x86_64 Linux test host")
        pins = self.pins()
        self.root.mkdir(mode=0o700)
        for filename, size, sha in pins["debs"]:
            archive = self.directory / Path(filename).name
            cached_input(dict(url="https://archive.ubuntu.com/ubuntu/" + filename, size_bytes=size, sha256=sha), archive)
            subprocess.run(["dpkg-deb", "-x", str(archive), str(self.root)], check=True, capture_output=True, timeout=60)
        self.env = dict(os.environ, LD_LIBRARY_PATH=":".join(str(self.root / p) for p in
            ("usr/lib/x86_64-linux-gnu", "lib/x86_64-linux-gnu")),
            QEMU_MODULE_DIR=str(self.root / "usr/lib/x86_64-linux-gnu/qemu"))
        version = subprocess.run([str(self.root / "usr/bin" / self.binary), "--version"],
            env=self.env, capture_output=True, text=True, timeout=30)
        if version.returncode or "version 8.2.2" not in version.stdout:
            raise ValueError("private QEMU cannot run: " + version.stderr[-2000:])

    def _cloud_input(self, local, expected):
        cached_input(expected, self.directory / local)

    def _prepare(self):
        self._prepare_tools()
        pins = self.pins()
        for local, (name, size, sha) in pins["cloud"].items():
            self._cloud_input(local, dict(url=pins["cloud_base"] + name, size_bytes=size, sha256=sha))
        with (self.directory / "work.raw").open("xb") as handle:
            handle.truncate(self.work_bytes)
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(self.directory / "guest-key")],
                       check=True, capture_output=True, timeout=30, **self._process_options())
        seed = self.directory / "seed"
        seed.mkdir(mode=0o700)
        public = (self.directory / "guest-key.pub").read_text().strip()
        config = dict(disable_root=False, ssh_pwauth=False,
                      users=[dict(name="root", lock_passwd=True, ssh_authorized_keys=[public])])
        (seed / "user-data").write_text("#cloud-config\n" + json.dumps(config))
        (seed / "meta-data").write_text(f"instance-id: {self.instance_id}\nlocal-hostname: rosy-system-guest\n")
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Seed, directory=str(seed)))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.ssh_port = _port()
        self.prepare_boot()
        self.stderr = (self.directory / "qemu-stderr.log").open("wb")
        self.process = subprocess.Popen(self.command(self.ssh_port, self.server.server_port), env=self.env,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=self.stderr, **self._process_options(session=True))

    def _ssh(self, command, *, timeout=30, data=None):
        return subprocess.run(["ssh", "-p", str(self.ssh_port), "-i", str(self.directory / "guest-key"),
            "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-o", "ConnectTimeout=3", "-o", "LogLevel=ERROR",
            "-o", "StrictHostKeyChecking=accept-new", "-o", "UserKnownHostsFile=" + str(self.directory / "known-hosts"),
            "root@127.0.0.1", command], input=data, capture_output=True, timeout=timeout)

    def run(self, command, *, timeout=300, data=None):
        result = self._ssh(command, timeout=timeout, data=data)
        if result.returncode:
            stdout = result.stdout.decode("utf-8", errors="replace")[-6000:]
            stderr = result.stderr.decode("utf-8", errors="replace")[-6000:]
            raise ValueError("guest command failed:\n" + stdout + "\n" + stderr)
        return result.stdout.decode("utf-8", errors="replace")

    def provision_source(self, source, *, revision=None):
        if self.run("cat /var/lib/cloud/data/instance-id").strip() != self.instance_id:
            raise ValueError("guest instance does not belong to this SYSTEM fixture")
        raw = committed_archive(Path(source), revision) if revision is not None else None
        self.run("test ! -e /run/rosy-system-guest")
        self.run(f'test "$(blockdev --getsize64 /dev/vdb)" = {self.work_bytes}')
        self.run("! findmnt -rn -S /dev/vdb")
        self.run("mkfs.ext4 -F -q -m 0 -E lazy_itable_init=0,lazy_journal_init=0 /dev/vdb", timeout=300)
        self.run("mkdir -p /work")
        self.run("mount -o nodev,nosuid /dev/vdb /work")
        # All package/service mutations are inside the UUID-bound disposable guest.
        self.run("apt-get update -qq", timeout=600)
        self.run("DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=120 install -y -qq "
            "python3-pytest python3-yaml python3-cryptography openssl e2fsprogs dosfstools mtools util-linux udev "
            "squashfs-tools rauc=1.11.3-2 rsync", timeout=900)
        source = Path(source)
        content = io.BytesIO()
        def public_source(info):
            if "__pycache__" in Path(info.name).parts or info.name.endswith(".pyc"):
                return None
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            return info
        if revision is None:
            # Test-PC snapshots have already been exported from the committed revision, without a Git database.
            with tarfile.open(fileobj=content, mode="w:gz", compresslevel=1) as archive:
                for name in SOURCE_PATHS:
                    archive.add(source / name, arcname=name, filter=public_source)
                for path in source.glob("*.yaml"):
                    archive.add(path, arcname=path.name, filter=public_source)
            raw = content.getvalue()
        if len(raw) > 128 * 1024**2:
            raise ValueError("SYSTEM source handoff exceeds its expected size")
        self.run("cat > /work/source.tar.gz", data=raw, timeout=300)
        if self.run("sha256sum /work/source.tar.gz").split()[0] != hashlib.sha256(raw).hexdigest():
            raise ValueError("SYSTEM source handoff digest differs")
        self.run("mkdir /work/source")
        self.run("tar -xzf /work/source.tar.gz -C /work/source", timeout=300)
        self.run("cat > /run/rosy-system-guest", data=self.instance_id.encode("ascii"))

    def __enter__(self):
        try:
            self._prepare()
            return self.wait_boot()
        except BaseException:
            self.close()
            raise

    def wait_boot(self):
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

    def _stop_process(self, *, force=False):
        os.killpg(self.process.pid, signal.SIGKILL if force else signal.SIGTERM)

    def close(self):
        if self.process is not None and self.process.poll() is None:
            self._stop_process()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._stop_process(force=True)
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


def _windows_private(path):
    """Check existing owner-only ACLs without changing operator files."""
    encoded_path = base64.b64encode(str(Path(path).absolute()).encode('utf-8')).decode('ascii')
    script = r'''
$ErrorActionPreference = 'Stop'
$target = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('PATH_BASE64'))
$item = Get-Item -LiteralPath $target -Force
if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'reparse point' }
$acl = Get-Acl -LiteralPath $target
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
if ($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $sid.Value) { throw 'owner differs' }
foreach ($rule in $acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
    if ($rule.AccessControlType -eq 'Allow' -and $rule.IdentityReference.Value -ne $sid.Value) {
        throw 'non-owner access'
    }
}
Write-Output 'ROSY_PRIVATE'
'''.replace('PATH_BASE64', encoded_path)
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand',
                             base64.b64encode(script.encode('utf-16le')).decode('ascii')],
                            capture_output=True, timeout=30, creationflags=0x08000000)
    if result.returncode or result.stdout.strip() != b'ROSY_PRIVATE':
        raise ValueError('Windows tools input requires an owner-only ACL')


class WindowsGuest(Guest):
    """Operator preparation in an owned tools VM; production keys remain on Windows."""
    work_bytes = 32 * 1024**3

    def __init__(self, directory, *, cache=None):
        self.cache = Path(cache) if cache is not None else Path(os.environ['LOCALAPPDATA']) / 'Rosy/os-tools'
        self.cache = self.cache.absolute()
        if (self.cache.resolve() != self.cache or self.cache == Path(self.cache.anchor)
                or any(c in str(self.cache) for c in ',\r\n\0')):
            raise ValueError('Windows tools cache path is unsafe')
        super().__init__(directory)

    def _check_workspace(self):
        _windows_private(self.directory)

    def _qemu_files(self):
        root = self.root
        return root / 'qemu-system-x86_64.exe', root / 'share', root / 'share/bios-256k.bin'

    def _process_options(self, *, session=False):
        return dict(creationflags=0x08000000)

    def _prepare_tools(self):
        if os.name != 'nt' or platform.machine().lower() not in ('amd64', 'x86_64'):
            raise ValueError('operator tools require native x86_64 Windows')
        _windows_private(self.cache)
        self._extract_tools()
        binary, share, bios = self._qemu_files()
        for path in (binary, bios):
            self._private_file(path)
        _windows_private(binary.parent)
        _windows_private(share)
        self.env = dict(os.environ)
        version = subprocess.run([str(binary), '--version'], env=self.env, capture_output=True,
                                 timeout=30, **self._process_options())
        if version.returncode or b'11.1.0 (v11.1.0-12130-ge470268ff4)' not in version.stdout:
            raise ValueError('private Windows QEMU version differs')

    def _extract_tools(self):
        def capture(source, target, expected, algorithm):
            self._private_file(source)
            with source.open('rb') as incoming, target.open('xb') as outgoing:
                digest, total = hashlib.new(algorithm), 0
                while chunk := incoming.read(min(2 * 1024**2, expected[0] - total + 1)):
                    total += len(chunk)
                    if total > expected[0]:
                        raise ValueError('Windows tools input size or digest differs')
                    digest.update(chunk)
                    outgoing.write(chunk)
            if (total, digest.hexdigest()) != expected:
                raise ValueError('Windows tools input size or digest differs')

        extractor = self.directory / 'extractor'
        # Inherit the verified owner-only ACL; Windows mode 0700 adds other privileged principals.
        extractor.mkdir()
        _windows_private(extractor)
        for name, expected in WINDOWS_7ZIP.items():
            capture(self.cache / '7zip-26.05' / name, extractor / name, expected, 'sha256')
        package = self.directory / 'qemu-package.exe'
        capture(self.cache / 'qemu-w64-setup-20260811.exe', package, WINDOWS_QEMU_PACKAGE, 'sha512')
        self.root.mkdir()
        _windows_private(self.root)
        subprocess.run([str(extractor / '7z.exe'), 'x', str(package), '-o' + str(self.root),
                        '-y', '-bso0', '-bsp0'], capture_output=True, check=True, timeout=180,
                       **self._process_options())

    def _private_file(self, path):
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('Windows tools input is not a private regular file')
        _windows_private(path)

    def _cloud_input(self, local, expected):
        source = self.cache / local
        self._private_file(source)
        download({**expected, 'url': source.as_uri()}, self.directory / local)

    def provision_source(self, source, *, revision=None):
        if not isinstance(revision, str) or not re.fullmatch('[0-9a-f]{40}', revision):
            raise ValueError('operator source requires an exact commit revision')
        return super().provision_source(source, revision=revision)

    def _ssh_authority(self):
        if self.process is None or self.process.poll() is not None:
            raise ValueError('owned Windows tools guest is not running')
        console = self.directory / 'guest-console.log'
        if not console.exists():
            return None
        self._private_file(console)
        with console.open('rb') as stream:
            raw = stream.read(4 * 1024**2 + 1)
        if len(raw) > 4 * 1024**2:
            raise ValueError('owned console exceeds its bound')
        blocks = re.findall(rb'-----BEGIN SSH HOST KEY KEYS-----\r?\n(.*?)-----END SSH HOST KEY KEYS-----', raw, re.S)
        if not blocks:
            return None
        keys = re.findall(rb'^ssh-ed25519 ([A-Za-z0-9+/=]+)(?:[ \t][^\r\n]*)?\r?$', blocks[0], re.M)
        if len(blocks) != 1 or len(keys) != 1:
            raise ValueError('owned console host key is ambiguous')
        try:
            blob = base64.b64decode(keys[0], validate=True)
        except ValueError as error:
            raise ValueError('invalid owned console host key') from error
        if len(blob) != 51 or blob[:19] != b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20':
            raise ValueError('invalid owned console Ed25519 host key')
        known = self.directory / 'known-hosts'
        expected = f'[127.0.0.1]:{self.ssh_port} ssh-ed25519 '.encode() + keys[0] + b'\n'
        if known.exists() or known.is_symlink():
            self._private_file(known)
            if known.read_bytes() != expected:
                raise ValueError('owned guest host key changed')
        else:
            with known.open('xb') as stream:
                stream.write(expected)
        return ['-F', 'none',
            '-i', str(self.directory / 'guest-key'), '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
            '-o', 'ForwardAgent=no', '-o', 'ClearAllForwardings=yes', '-o', 'ControlMaster=no',
            '-o', 'ControlPath=none', '-o', 'ConnectTimeout=3', '-o', 'LogLevel=ERROR',
            '-o', 'StrictHostKeyChecking=yes', '-o', 'HostKeyAlgorithms=ssh-ed25519',
            '-o', 'GlobalKnownHostsFile=' + os.devnull, '-o', 'UserKnownHostsFile=' + known.as_posix()]

    def _ssh(self, command, *, timeout=30, data=None):
        authority = self._ssh_authority()
        if authority is None:
            return subprocess.CompletedProcess([], 255, b'', b'waiting for owned console host key')
        result = subprocess.run(['ssh', *authority, '-p', str(self.ssh_port),
            'root@127.0.0.1', command], input=data, capture_output=True, timeout=timeout,
            **self._process_options())
        if self.process.poll() is not None:
            raise ValueError('owned Windows tools guest exited during SSH')
        return result

    def copy_from(self, remote, target, *, size_bytes, sha256):
        if (not isinstance(remote, str)
                or not re.fullmatch(r'/work/finalized/[A-Za-z0-9][A-Za-z0-9._-]{0,127}', remote)
                or type(size_bytes) is not int or not 1 <= size_bytes <= 16 * 1024**3
                or not isinstance(sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', sha256)):
            raise ValueError('invalid finalized guest artifact reference')
        if not isinstance(target, (str, os.PathLike)):
            raise ValueError('invalid operator artifact destination')
        target = Path(target).absolute()
        if target.exists() or target.is_symlink():
            raise FileExistsError('operator artifact destination already exists')
        if target.parent.resolve() != target.parent:
            raise ValueError('operator artifact parent redirects')
        _windows_private(target.parent)
        authority = self._ssh_authority()
        if authority is None:
            raise ValueError('owned console host key is not available')
        partial = target.with_name('.' + target.name + '-' + uuid.uuid4().hex + '.part')
        with partial.open('xb'):
            pass
        try:
            result = subprocess.run(['scp', '-q', *authority, '-P', str(self.ssh_port),
                'root@127.0.0.1:' + remote, str(partial)], stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=8 * 3600,
                **self._process_options())
            if self.process.poll() is not None:
                raise ValueError('owned Windows tools guest exited during transfer')
            if result.returncode:
                raise ValueError('finalized guest artifact transfer failed')
            self._private_file(partial)
            if partial.stat().st_size != size_bytes:
                raise ValueError('transferred artifact size differs')
            with partial.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            if digest != sha256:
                raise ValueError('transferred artifact digest differs')
            if self.process.poll() is not None:
                raise ValueError('owned Windows tools guest exited before publication')
            # A same-directory hard link publishes atomically without replacing a raced destination.
            os.link(partial, target)
        finally:
            partial.unlink(missing_ok=True)
        return target

    def _stop_process(self, *, force=False):
        self.process.kill() if force else self.process.terminate()
