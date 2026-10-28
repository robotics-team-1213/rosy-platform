"""Bounded loopback handoff: real HTTP and receiver execution in a temporary /work."""
import ast
import hashlib
import importlib
import io
import json
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import pytest


def module():
    return importlib.import_module('tools.release.os_public_inputs')


@pytest.fixture
def distribution(tmp_path):
    dist = tmp_path / 'dist'
    dist.mkdir()
    contents = {'manifest.json': b'{"kind":"fixture"}\n', 'factory-release/fixture/metadata.json': b'public nested record'}
    for name, raw in contents.items():
        path = dist / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    snapshot = dict(inputs={}, entries={name: hashlib.sha256(raw).hexdigest() for name, raw in contents.items()},
        sizes={name: len(raw) for name, raw in contents.items()}, checksums=b'captured signed checksums\n',
        signature=b'captured signature\n', public_key=b'captured public authority\n')
    return dist, snapshot, b'captured public CMS certificate\n', contents


def local_url(description, route):
    assert urlsplit(description['base_url']).hostname == '10.0.2.2'
    return 'http://127.0.0.1:' + str(urlsplit(description['base_url']).port) + '/' + route


def test_exact_descriptor_files_and_immutable_public_authority_bytes(distribution):
    dist, snapshot, certificate, contents = distribution
    captured = dict(contents, **{'SHA256SUMS': snapshot['checksums'], 'SHA256SUMS.sig': snapshot['signature'],
        '__operator__/release.pem': snapshot['public_key'], '__operator__/cms.pem': certificate})
    with module().serve_inputs(dist, snapshot, certificate) as description:
        snapshot.update(checksums=b'changed', signature=b'changed', public_key=b'changed')
        snapshot['entries']['manifest.json'] = '0' * 64
        for record in description['files']:
            route = record['route']
            expected_destination = {'__operator__/release.pem': '/work/operator-release.pub.pem',
                                    '__operator__/cms.pem': '/work/operator-cms.pem'}.get(route, '/work/dist/' + route)
            assert record == dict(route=route, destination=expected_destination,
                size_bytes=len(captured[route]), sha256=hashlib.sha256(captured[route]).hexdigest())
            with urlopen(local_url(description, route), timeout=3) as response:
                assert response.read() == captured[route]
        assert {record['route'] for record in description['files']} == set(captured)


def test_byte_ranges_return_exact_authenticated_size_and_canonical_download_can_receive(distribution, tmp_path):
    dist, snapshot, certificate, contents = distribution
    from tools.release.os_tools_vm import download
    with module().serve_inputs(dist, snapshot, certificate) as description:
        request = Request(local_url(description, 'manifest.json'), headers={'Range': 'bytes=2-7'})
        with urlopen(request, timeout=3) as response:
            assert response.status == 206
            assert response.headers['Content-Range'] == 'bytes 2-7/' + str(len(contents['manifest.json']))
            assert response.headers['Content-Length'] == '6'
            assert response.read() == contents['manifest.json'][2:8]
        record = next(row for row in description['files'] if row['route'] == 'manifest.json')
        download(dict(url=local_url(description, record['route']), size_bytes=record['size_bytes'], sha256=record['sha256']), tmp_path / 'received')
        assert (tmp_path / 'received').read_bytes() == contents['manifest.json']
        for value in ('bytes=999-1000', 'bytes=0-1,3-4', 'not-a-range'):
            with pytest.raises(HTTPError) as error:
                urlopen(Request(local_url(description, 'manifest.json'), headers={'Range': value}), timeout=3)
            assert error.value.code == 416


@pytest.mark.parametrize('route', ['', 'unknown', '../outside', '%2e%2e/outside', '%6danifest.json', 'manifest.json?x=1',
    'factory-release/', 'factory-release//fixture/metadata.json', 'factory-release/../manifest.json', '__operator__/unknown', '%2fmanifest.json'])
def test_unknown_or_noncanonical_urls_never_expose_files(distribution, route):
    dist, snapshot, certificate, _ = distribution
    (dist / 'private.txt').write_text('not in the authenticated set')
    with module().serve_inputs(dist, snapshot, certificate) as description:
        with pytest.raises(HTTPError) as error:
            urlopen(local_url(description, route), timeout=3)
        assert error.value.code in (400, 404)


@pytest.mark.parametrize('kind', ['symlink', 'directory', 'fifo', 'changed_size'])
def test_changed_or_nonregular_distribution_files_are_refused(distribution, tmp_path, kind):
    import os
    dist, snapshot, certificate, contents = distribution
    path = dist / 'manifest.json'
    path.unlink()
    if kind == 'symlink':
        outside = tmp_path / 'outside'
        outside.write_bytes(contents['manifest.json'])
        path.symlink_to(outside)
    elif kind == 'directory': path.mkdir()
    elif kind == 'fifo': os.mkfifo(path)
    else: path.write_bytes(contents['manifest.json'] + b'changed')
    with pytest.raises(ValueError):
        with module().serve_inputs(dist, snapshot, certificate): pytest.fail('accepted unsafe input')


def test_files_replaced_after_server_start_are_rechecked(distribution, tmp_path):
    dist, snapshot, certificate, contents = distribution
    outside = tmp_path / 'outside'
    outside.write_bytes(contents['manifest.json'])
    with module().serve_inputs(dist, snapshot, certificate) as description:
        path = dist / 'manifest.json'
        path.unlink()
        path.symlink_to(outside)
        with pytest.raises(HTTPError): urlopen(local_url(description, 'manifest.json'), timeout=3)


def test_parent_swap_after_ancestor_checks_cannot_stream_an_outside_file(distribution, tmp_path, monkeypatch):
    dist, snapshot, certificate, contents = distribution
    route = 'factory-release/fixture/metadata.json'
    path = dist / route
    outside = tmp_path / 'outside'
    outside.mkdir()
    private = b'S' * len(contents[route])
    assert private != contents[route]
    (outside / path.name).write_bytes(private)
    original_lstat = Path.lstat
    swapped = False

    def swap_before_leaf_stat(candidate, *args, **kwargs):
        nonlocal swapped
        if candidate == path and not swapped:
            path.parent.rename(tmp_path / 'original-parent')
            path.parent.symlink_to(outside, target_is_directory=True)
            swapped = True
        return original_lstat(candidate, *args, **kwargs)

    with module().serve_inputs(dist, snapshot, certificate) as description:
        monkeypatch.setattr(Path, 'lstat', swap_before_leaf_stat)
        try:
            with urlopen(local_url(description, route), timeout=3) as response:
                raw = response.read()
        except HTTPError:
            raw = None
        assert swapped, 'the parent replacement must occur at the real leaf-stat boundary'
        assert raw in (None, contents[route]), 'an outside file was streamed before receiver digest verification'


def test_same_size_changed_content_is_refused_before_listening(distribution):
    dist, snapshot, certificate, contents = distribution
    (dist / 'manifest.json').write_bytes(b'X' * len(contents['manifest.json']))
    with pytest.raises(ValueError):
        with module().serve_inputs(dist, snapshot, certificate):
            pytest.fail('file bytes were not bound to the authenticated snapshot')


@pytest.mark.parametrize('route', ['__operator__/release.pem', '__operator__/cms.pem', 'SHA256SUMS', 'SHA256SUMS.sig', '../outside', '/absolute', 'x/../manifest.json', 'x%2fy', 'x?query', 'x\\y'])
def test_snapshot_route_collisions_and_escapes_are_refused(distribution, route):
    dist, snapshot, certificate, _ = distribution
    snapshot['entries'][route] = '0' * 64
    snapshot['sizes'][route] = 1
    with pytest.raises(ValueError):
        with module().serve_inputs(dist, snapshot, certificate): pytest.fail('accepted unsafe snapshot route')


def test_context_cleanup_closes_the_listener_even_on_failure(distribution):
    dist, snapshot, certificate, _ = distribution
    with pytest.raises(RuntimeError):
        with module().serve_inputs(dist, snapshot, certificate) as description:
            port = urlsplit(description['base_url']).port
            raise RuntimeError('caller failed')
    with socket.socket() as connection:
        connection.settimeout(1)
        assert connection.connect_ex(('127.0.0.1', port)) != 0


def run_receiver(script, description, tmp_path, monkeypatch):
    # Replace only the fixed guest /work root; execute the real validation and filesystem code.
    description = json.loads(json.dumps(description))
    for row in description['files']:
        if row['destination'] == '/work' or row['destination'].startswith('/work/'):
            row['destination'] = str(tmp_path) + row['destination'][5:]
    class WorkRoot(ast.NodeTransformer):
        def visit_Constant(self, node):
            if isinstance(node.value, str) and (node.value == '/work' or node.value.startswith('/work/')):
                return ast.copy_location(ast.Constant(str(tmp_path) + node.value[5:]), node)
            return node
    calls = []
    def download(expected, destination):
        assert Path(destination).is_relative_to(tmp_path)
        calls.append((expected, str(destination)))
        Path(destination).write_bytes(b'received')
    monkeypatch.setitem(sys.modules, 'os_tools_vm', SimpleNamespace(download=download))
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(description)))
    monkeypatch.setattr(sys, 'path', list(sys.path))
    tree = WorkRoot().visit(ast.parse(script))
    exec(compile(ast.fix_missing_locations(tree), '<guest receiver>', 'exec'), {'__name__': '__main__'})
    return calls


def test_guest_receiver_uses_only_canonical_download_and_fixed_destinations(distribution, tmp_path, monkeypatch):
    dist, snapshot, certificate, _ = distribution
    with module().serve_inputs(dist, snapshot, certificate) as description:
        calls = run_receiver(module().RECEIVE_SCRIPT, description, tmp_path / 'guest', monkeypatch)
    assert len(calls) == len(description['files'])
    for row, (expected, destination) in zip(description['files'], calls):
        assert expected == dict(url=description['base_url'] + '/' + row['route'], size_bytes=row['size_bytes'], sha256=row['sha256'])
        assert destination == str(tmp_path / 'guest') + row['destination'][5:]


@pytest.mark.parametrize('fault', ['base', 'route', 'destination', 'authority_destination', 'size', 'digest', 'duplicate'])
def test_guest_receiver_rejects_descriptor_escape_before_any_download(distribution, tmp_path, monkeypatch, fault):
    dist, snapshot, certificate, _ = distribution
    with module().serve_inputs(dist, snapshot, certificate) as description:
        if fault == 'base': description['base_url'] = 'http://example.invalid:80'
        elif fault == 'route': description['files'][0]['route'] = '../outside'
        elif fault == 'destination': description['files'][0]['destination'] = '/etc/outside'
        elif fault == 'authority_destination':
            next(row for row in description['files'] if row['route'] == '__operator__/cms.pem')['destination'] = '/work/dist/cms.pem'
        elif fault == 'size': description['files'][0]['size_bytes'] = True
        elif fault == 'digest': description['files'][0]['sha256'] = 'not-a-digest'
        else: description['files'].append(dict(description['files'][0]))
        guest = tmp_path / 'guest'
        with pytest.raises(ValueError): run_receiver(module().RECEIVE_SCRIPT, description, guest, monkeypatch)
        assert not guest.exists()
