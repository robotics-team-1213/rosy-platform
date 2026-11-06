"""Only frozen policy views enter a passive LeRobot training folder."""
from pathlib import Path
import copy
import sys
from types import ModuleType, SimpleNamespace

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_passive_recording import kept_episode
import passive_export as exporter


def test_export_features_preserve_order_and_filter_review_only_views(tmp_path):
    seal,profile,_,_=kept_episode(tmp_path/'episode')
    features=exporter.dataset_features(seal)
    assert features['observation.state']['shape']==(4,)
    assert features['action']['names']==['arm_0/j0','arm_0/j1','arm_1/j0','arm_1/j1']
    assert features['observation.images.top']['shape']==(16,16,3)
    assert 'observation.images.wrist' not in features
    assert 'observation.images.preview' not in features


def test_export_rejects_tampered_or_insufficient_raw_before_sdk_import(tmp_path,monkeypatch):
    kept_episode(tmp_path/'episode')
    monkeypatch.setattr(exporter.importlib.metadata,'version',lambda *_:pytest.fail('SDK touched before raw validation'))
    with pytest.raises(ValueError):
        exporter.export([tmp_path/'episode'],tmp_path/'output')
    assert not (tmp_path/'output').exists()
    image=next((tmp_path/'episode').rglob('*.jpg'))
    image.write_bytes(b'corrupt')
    with pytest.raises(ValueError):
        exporter.export([tmp_path/'episode',tmp_path/'episode'],tmp_path/'output')
    assert not (tmp_path/'output').exists()


def test_one_frame_reserve_counts_policy_pixels_without_a_cumulative_frame_limit(tmp_path):
    seal,_,_,_=kept_episode(tmp_path/'episode')
    budget=exporter.frame_budget(seal)
    longer=copy.deepcopy(seal)
    longer['frames']=100000
    assert exporter.frame_budget(longer)==budget
    review=copy.deepcopy(seal)
    review['config']['profile']['cameras'][1]['shape']=[3,1024,1024]
    assert exporter.frame_budget(review)==budget
    policy=copy.deepcopy(seal)
    policy['config']['profile']['cameras'][0]['shape']=[3,32,32]
    assert exporter.frame_budget(policy)>budget


def test_storage_cap_tracks_actual_png_bytes_and_episode_copy_reserve(tmp_path,monkeypatch):
    output=tmp_path/'output'
    output.mkdir()
    png=output/'frame.png'
    png.write_bytes(b'1234')
    key='observation.images.top'
    child=SimpleNamespace(episode_buffer={key:[str(png)]})
    budget=exporter.StorageBudget(output,[key],65536)
    budget.after_frame(child)
    assert budget.episode_bytes==4 and budget.saved_bytes==0
    calls=[]
    monkeypatch.setattr(exporter.recording,'require_space',lambda root,needed=0:calls.append(needed))
    budget.before_episode()
    assert calls==[8]
    budget.finish_episode()
    assert budget.saved_bytes==4 and budget.episode_bytes==0
    budget.saved_bytes=2*1024**3-3
    with pytest.raises(ValueError,match='2 GiB|budget'):
        budget.after_frame(child)


def test_export_space_admission_happens_before_sdk_import(tmp_path,monkeypatch):
    kept_episode(tmp_path/'first')
    kept_episode(tmp_path/'second')
    monkeypatch.setattr('shutil.disk_usage',lambda *_:SimpleNamespace(free=0))
    monkeypatch.setattr(exporter.importlib.metadata,'version',lambda *_:pytest.fail('SDK touched before disk admission'))
    with pytest.raises(ValueError,match='space|reserve'):
        exporter.export([tmp_path/'first',tmp_path/'second'],tmp_path/'output')
    assert not (tmp_path/'output').exists()


def test_export_disk_loss_between_frames_stops_synchronous_writer_and_preserves_sources(tmp_path,monkeypatch):
    seals=[kept_episode(tmp_path/name)[0] for name in ('first','second')]
    free=[10**12]
    monkeypatch.setattr('shutil.disk_usage',lambda *_:SimpleNamespace(free=free[0]))
    monkeypatch.setattr(exporter.importlib.metadata,'version',lambda *_:'0.4.4')
    written=[]
    finalized=[]
    class Writer:
        def __init__(self,keys):
            self.episode_buffer={key:[] for key in keys}
        def add_frame(self,values):
            written.append(values)
            (tmp_path/'output'/'partial.txt').write_bytes(b'preserved staged data')
            for index,key in enumerate(self.episode_buffer):
                png=tmp_path/'output'/f'{index}.png'
                png.write_bytes(b'actual PNG byte-count fixture')
                self.episode_buffer[key].append(str(png))
            free[0]=0
        def finalize(self):
            finalized.append(True)
    class Dataset:
        @staticmethod
        def create(*_,**options):
            assert options['image_writer_threads']==0
            Path(options['root']).mkdir()
            return Writer([key for key in options['features'] if key.startswith('observation.images.')])
    for name in ('lerobot','lerobot.datasets'):
        module=ModuleType(name)
        module.__path__=[]
        monkeypatch.setitem(sys.modules,name,module)
    monkeypatch.setitem(sys.modules,'lerobot.datasets.lerobot_dataset',SimpleNamespace(LeRobotDataset=Dataset))
    with pytest.raises(ValueError,match='space|reserve'):
        exporter.export([tmp_path/'first',tmp_path/'second'],tmp_path/'output')
    assert len(written)==1 and finalized==[True]
    assert (tmp_path/'output'/'partial.txt').read_bytes()==b'preserved staged data'
    assert not (tmp_path/'output.receipt.json').exists()
    assert [exporter.recording.verify(tmp_path/name) for name in ('first','second')]==seals
