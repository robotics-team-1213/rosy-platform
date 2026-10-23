import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def module(monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'hub_sync.py'
    assert path.is_file(), 'reviewed Hub bundle sync is not implemented'
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location('omx_hub_sync', path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture
def bundle(module, tmp_path):
    source = tmp_path / 'source'
    (source / 'meta').mkdir(parents=True)
    (source / 'meta/info.json').write_text('{}')
    (source / 'README.md').write_text('Reviewed dataset')
    return module.prepare_bundle(source, tmp_path / 'bundle', 'team/omx', 'dataset',
                                 ['meta/info.json', 'README.md'])


def test_preview_snapshots_only_selected_files(module, bundle):
    manifest = json.loads((bundle / 'manifest.json').read_text())
    assert manifest['repo_id'] == 'team/omx'
    assert set(manifest['files']) == {'README.md', 'meta/info.json'}
    assert not (bundle / 'receipt.json').exists()


def test_omx_export_cannot_be_silently_reduced_to_generic_dataset_files(module, tmp_path):
    source = tmp_path/'source'
    (source/'meta').mkdir(parents=True)
    (source/'meta/info.json').write_text('{}')
    (source/'rosy_export.json').write_text('{"status":"verified"}')
    output = tmp_path/'bundle'
    with pytest.raises(ValueError, match='complete OMX export'):
        module.prepare_bundle(source, output, 'team/omx', 'dataset', ['meta/info.json'])
    assert not output.exists()


@pytest.mark.parametrize('path', ['../secret', '/secret', 'private/notes.json', '.env', 'meta/../../secret'])
def test_upload_bundle_refuses_private_and_escaping_files(module, tmp_path, path):
    with pytest.raises(ValueError):
        module.prepare_bundle(tmp_path, tmp_path.parent / (tmp_path.name + '-out'),
                              'team/omx', 'dataset', [path])


class FakeHub:
    def __init__(self, private=True):
        self.private = private
        self.uploads = 0
        self.files = {}

    def repo_info(self, **kwargs):
        return SimpleNamespace(private=self.private, sha='a' * 40)

    def create_commit(self, **kwargs):
        self.uploads += 1
        assert kwargs['parent_commit'] == 'a' * 40
        self.files = {op.path_in_repo: Path(op.path_or_fileobj).read_bytes() for op in kwargs['operations']}
        return SimpleNamespace(oid='b' * 40)


def test_public_repo_is_rejected_before_upload(module, bundle):
    hub = FakeHub(private=False)
    with pytest.raises(ValueError, match='private'):
        module.upload_bundle(bundle, api=hub, operation=SimpleNamespace)
    assert hub.uploads == 0


def test_changed_bundle_is_rejected_before_upload(module, bundle):
    (bundle / 'payload/meta/info.json').write_text('changed')
    hub = FakeHub()
    with pytest.raises(ValueError, match='hash'):
        module.upload_bundle(bundle, api=hub, operation=SimpleNamespace)
    assert hub.uploads == 0


def test_receipt_requires_sha_pinned_download_and_matching_bytes(module, bundle):
    hub = FakeHub()

    def download(**kwargs):
        assert kwargs['revision'] == 'b' * 40
        target = Path(kwargs['local_dir'])
        for path, payload in hub.files.items():
            file = target / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(payload)
        return str(target)

    receipt = module.upload_bundle(bundle, api=hub, operation=SimpleNamespace, downloader=download)
    assert receipt['revision'] == 'b' * 40
    assert receipt['bytes_verified'] is True
    assert receipt['reader_verified'] is False
    assert json.loads((bundle / 'receipt.json').read_text()) == receipt


def test_network_failure_never_writes_success_receipt(module, bundle):
    def failed(**kwargs):
        raise ConnectionError('offline')
    with pytest.raises(ConnectionError):
        module.upload_bundle(bundle, api=FakeHub(), operation=SimpleNamespace, downloader=failed)
    assert not (bundle / 'receipt.json').exists()
    assert (bundle / 'payload/meta/info.json').is_file()


def test_interrupted_readback_retries_same_commit_and_rejects_corruption(module, bundle):
    hub = FakeHub()

    def interrupted(**kwargs):
        raise ConnectionError('offline')

    with pytest.raises(ConnectionError):
        module.upload_bundle(bundle, api=hub, operation=SimpleNamespace, downloader=interrupted)

    def download(corrupt=False, **kwargs):
        assert kwargs['revision'] == 'b' * 40
        for name, payload in hub.files.items():
            path = Path(kwargs['local_dir']) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'corrupt' if corrupt else payload)

    with pytest.raises(ValueError, match='hash'):
        module.upload_bundle(bundle, api=hub, operation=SimpleNamespace,
                             downloader=lambda **kwargs: download(corrupt=True, **kwargs))
    assert not (bundle / 'receipt.json').exists()
    receipt = module.upload_bundle(bundle, api=hub, operation=SimpleNamespace, downloader=download)
    assert receipt['bytes_verified'] and hub.uploads == 1
