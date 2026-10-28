"""Prepare public Windows OS tools without running installers or handling keys."""
from __future__ import annotations

import base64
import contextlib
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
from urllib.request import urlopen
import uuid

if __package__:
    from . import os_tools_vm as vm
else:
    import os_tools_vm as vm

HIDDEN = 0x08000000
MSI = dict(filename='7z2605-x64.msi',
    url='https://github.com/ip7z/7zip/releases/download/26.05/7z2605-x64.msi',
    size_bytes=2008576, sha256='3fe4ab99fa15629c652944309a2b2bc6e41fc933fc6b63f5df1ebcf3aea68263')
QEMU = dict(filename='qemu-w64-setup-20260811.exe',
    url='https://qemu.weilnetz.de/w64/qemu-w64-setup-20260811.exe',
    size_bytes=vm.WINDOWS_QEMU_PACKAGE[0], sha512=vm.WINDOWS_QEMU_PACKAGE[1])


def _require_windows():
    if os.name != 'nt' or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise ValueError('public operator tools require native x86_64 Windows')


def _ensure_directory(path):
    path = Path(path).absolute()
    if path.resolve() != path or path == Path(path.anchor):
        raise ValueError('operator cache path redirects or names a filesystem root')
    if path.exists():
        if not path.is_dir():
            raise ValueError('operator cache is not a directory')
        vm._windows_private(path)
        return
    path.mkdir(parents=True)
    encoded = base64.b64encode(str(path).encode('utf-8')).decode('ascii')
    script = r'''
$ErrorActionPreference = 'Stop'
$target = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('PATH_BASE64'))
$owner = [Security.Principal.WindowsIdentity]::GetCurrent().User
$access = New-Object Security.AccessControl.DirectorySecurity
$access.SetOwner($owner)
$access.SetAccessRuleProtection($true, $false)
$access.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($owner, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')))
Set-Acl -LiteralPath $target -AclObject $access
'''.replace('PATH_BASE64', encoded)
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand',
        base64.b64encode(script.encode('utf-16le')).decode('ascii')], capture_output=True,
        timeout=30, creationflags=HIDDEN)
    if result.returncode:
        raise ValueError('new operator cache ACL creation failed')
    vm._windows_private(path)


def _private_file(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError('public tools input must be a private regular file')
    vm._windows_private(path)
    return info


def _verify(path, expected):
    info = _private_file(path)
    algorithm = 'sha256' if 'sha256' in expected else 'sha512'
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, algorithm).hexdigest()
    if info.st_size != expected['size_bytes'] or digest != expected[algorithm]:
        raise ValueError('public tools input size or digest differs')


def _ensure_input(expected, target):
    target = Path(target)
    vm._windows_private(target.parent)
    if target.exists() or target.is_symlink():
        _verify(target, expected)
        return
    try:
        if 'sha256' in expected:
            vm.download(expected, target)
        else:
            temporary = target.with_name('.' + target.name + '-' + uuid.uuid4().hex)
            try:
                with urlopen(expected['url'], timeout=30) as source, temporary.open('xb') as output:
                    digest, total = hashlib.sha512(), 0
                    while chunk := source.read(min(2 * 1024**2, expected['size_bytes'] - total + 1)):
                        total += len(chunk)
                        if total > expected['size_bytes']:
                            raise ValueError('public tools archive exceeds its pinned size')
                        digest.update(chunk)
                        output.write(chunk)
                    if total != expected['size_bytes'] or digest.hexdigest() != expected['sha512']:
                        raise ValueError('public tools archive size or digest differs')
                    output.flush()
                    os.fsync(output.fileno())
                temporary.rename(target)
            finally:
                temporary.unlink(missing_ok=True)
        _verify(target, expected)
    except Exception as error:
        # Network exceptions can contain redirected or signed URLs.
        raise ValueError('public tools download failed: ' + type(error).__name__) from None


def _msi_cab(package, destination):
    """Read only product.cab through the Windows Installer database API."""
    api = ctypes.WinDLL('msi', winmode=0x00000800)
    handle = ctypes.c_uint
    pointer = ctypes.POINTER(handle)
    for name, args in {
        'MsiOpenDatabaseW': [ctypes.c_wchar_p, ctypes.c_void_p, pointer],
        'MsiDatabaseOpenViewW': [handle, ctypes.c_wchar_p, pointer],
        'MsiViewExecute': [handle, handle], 'MsiViewFetch': [handle, pointer],
        'MsiRecordReadStream': [handle, ctypes.c_uint, ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)],
        'MsiViewClose': [handle], 'MsiCloseHandle': [handle],
    }.items():
        getattr(api, name).argtypes = args
        getattr(api, name).restype = ctypes.c_uint

    def checked(code):
        if code:
            raise ValueError('read-only MSI database operation failed')

    with contextlib.ExitStack() as cleanup:
        database, view, record = handle(), handle(), handle()
        checked(api.MsiOpenDatabaseW(str(package), None, ctypes.byref(database)))
        cleanup.callback(api.MsiCloseHandle, database)
        checked(api.MsiDatabaseOpenViewW(database,
            "SELECT `Data` FROM `_Streams` WHERE `Name`='product.cab'", ctypes.byref(view)))
        cleanup.callback(api.MsiCloseHandle, view)
        checked(api.MsiViewExecute(view, 0))
        cleanup.callback(api.MsiViewClose, view)
        checked(api.MsiViewFetch(view, ctypes.byref(record)))
        cleanup.callback(api.MsiCloseHandle, record)
        with destination.open('xb') as output:
            total = 0
            while True:
                buffer = ctypes.create_string_buffer(65536)
                size = ctypes.c_ulong(len(buffer))
                checked(api.MsiRecordReadStream(record, 1, buffer, ctypes.byref(size)))
                if not size.value:
                    break
                total += size.value
                if total > package.stat().st_size:
                    raise ValueError('MSI cabinet exceeds its verified package size')
                output.write(buffer.raw[:size.value])


def _check_extractor(directory):
    vm._windows_private(directory)
    for name, (size, digest) in vm.WINDOWS_7ZIP.items():
        _verify(directory / name, dict(size_bytes=size, sha256=digest))


def _extract_7zip(cache):
    cache = Path(cache).absolute()
    target = cache / '7zip-26.05'
    if target.exists() or target.is_symlink():
        _check_extractor(target)
        return
    _verify(cache / MSI['filename'], MSI)
    work = cache / ('.7zip-' + uuid.uuid4().hex)
    work.mkdir()
    try:
        vm._windows_private(work)
        cabinet = work / 'product.cab'
        _msi_cab(cache / MSI['filename'], cabinet)
        extracted = work / 'components'
        extracted.mkdir()
        vm._windows_private(extracted)
        subprocess.run(['tar.exe', '-xf', str(cabinet), '-C', str(extracted), '_7z.exe', '_7z.dll'],
            capture_output=True, check=True, timeout=60, creationflags=HIDDEN)
        for name in vm.WINDOWS_7ZIP:
            (extracted / ('_' + name)).rename(extracted / name)
        _check_extractor(extracted)
        extracted.rename(target)
    finally:
        if work.resolve().parent != cache.resolve():
            raise ValueError('temporary extractor directory escaped the operator cache')
        shutil.rmtree(work)


def prepare(cache=None):
    _require_windows()
    cache = Path(cache) if cache is not None else Path(os.environ['LOCALAPPDATA']) / 'Rosy/os-tools'
    cache = cache.absolute()
    _ensure_directory(cache)
    for expected in (MSI, QEMU):
        _ensure_input(expected, cache / expected['filename'])
    _extract_7zip(cache)
    pins = json.loads(vm.PINS.read_bytes())
    for local, (name, size, digest) in pins['cloud'].items():
        _ensure_input(dict(url=pins['cloud_base'] + name, size_bytes=size, sha256=digest), cache / local)
    return cache


if __name__ == '__main__':
    try:
        prepare()
        print('OS_TOOLS_READY: public pinned inputs verified; no installer action executed')
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit('OS_TOOLS_PREPARE_HOLD: ' + type(error).__name__) from None
