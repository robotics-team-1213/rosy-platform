"""Actual LeRobot reader; Hub transport is an in-memory immutable-byte fixture."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from test_hub_sync import FakeHub, module  # noqa: F401

ROOT = Path(__file__).resolve().parents[4]
for relative in ('learning/curation/omx', 'learning/curation/omx/test',
                 'contracts/foundation',
                 'middleware/devices/omx/adapter', 'middleware/devices/omx/adapter/test'):
    sys.path.insert(0, str(ROOT/relative))


@pytest.fixture
def exported(tmp_path):
    pytest.importorskip('lerobot')
    from sim_object_truth_fixture import fixture
    from sim_object_truth import build
    from lerobot_export import export_episode
    raw, native, episode = fixture(tmp_path, recording_fps=5)
    proof = build(raw, native, tmp_path/'proof')
    output = tmp_path/'export'
    export_episode(episode, output, 'team/omx', sim_ground_truth=proof['truth'])
    return output


def selected(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file())


def download(hub):
    def receive(**kwargs):
        assert kwargs['revision'] == 'b'*40
        for name, data in hub.files.items():
            path = Path(kwargs['local_dir'])/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    return receive


def test_actual_export_roundtrip_retains_truth_and_reopens_every_frame(module, exported, tmp_path):
    hub = FakeHub()
    bundle = module.prepare_bundle(exported, tmp_path/'bundle', 'team/omx', 'dataset', selected(exported))
    receipt = module.upload_bundle(bundle, api=hub, operation=SimpleNamespace, downloader=download(hub))
    assert receipt['bytes_verified'] and receipt['reader_verified']
    assert receipt['reader']['verified_frames'] == 28
    assert receipt['reader']['task_outcome_judge'] == 'sim_ground_truth'
    assert (bundle/'readback/rosy_sim_truth/truth.json').read_bytes() == (exported/'rosy_sim_truth/truth.json').read_bytes()
    for path in exported.glob('rosy_provenance/*/images/front/*.png'):
        assert (bundle/'readback'/path.relative_to(exported)).read_bytes() == path.read_bytes()


def test_source_image_omission_is_rejected_before_bundle_or_upload(module, exported, tmp_path):
    files = selected(exported)
    files.remove(next(name for name in files if name.endswith('.png')))
    output = tmp_path/'bundle'
    with pytest.raises(ValueError, match='complete OMX export'):
        module.prepare_bundle(exported, output, 'team/omx', 'dataset', files)
    assert not output.exists()


def test_reader_rejects_parquet_clocks_that_disagree_with_preserved_source(module, exported, tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    parquet, = exported.glob('data/**/*.parquet')
    table = pq.read_table(parquet)
    index = table.schema.get_field_index('source.capture_time_ns')
    field = table.schema.field(index)
    values = table.column(index).to_pylist()
    values[0] = [values[0][0]+1]
    pq.write_table(table.set_column(index, field, pa.array(values, type=field.type)), parquet)
    with pytest.raises(AssertionError, match='Arrays are not equal'):
        module.prepare_bundle(exported, tmp_path/'bundle', 'team/omx', 'dataset', selected(exported))
