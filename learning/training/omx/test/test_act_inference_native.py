"""Native safetensors byte consumption; no motion and no pretrained download."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[4]
sys.path[:0]=[str(ROOT/'learning/training/omx'),str(ROOT/'contracts/learning/src')]
from act_inference import ACTInference
from test_act_inference import artifact,observation
from rosy.contracts.learning import seal


def test_actual_act_weights_consume_snapshot_and_keep_queue_source(tmp_path):
    torch=pytest.importorskip('torch')
    pytest.importorskip('lerobot')
    from lerobot.policies.act.configuration_act import ACTConfig
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.configs.types import PolicyFeature,FeatureType
    torch.set_num_threads(2);torch.manual_seed(42761)
    root,doc,_=artifact(tmp_path)
    config=ACTConfig(input_features={'observation.state':PolicyFeature(FeatureType.STATE,(2,)),
                                    'observation.images.front':PolicyFeature(FeatureType.VISUAL,(3,8,8))},
        output_features={'action':PolicyFeature(FeatureType.ACTION,(2,))},chunk_size=4,n_action_steps=4,
        dim_model=64,n_heads=4,dim_feedforward=256,n_encoder_layers=1,n_decoder_layers=1,
        use_vae=False,dropout=0.,pretrained_backbone_weights=None,device='cpu')
    model=ACTPolicy(config);model.save_pretrained(root/'policy')
    doc['files']=[dict(path=p.relative_to(root).as_posix(),bytes=p.stat().st_size,
                       sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted((root/'policy').iterdir())]
    doc=seal(doc);(root/'policy-artifact.json').write_text(json.dumps(doc),encoding='utf-8')
    engine=ACTInference(root,doc['revision'],monotonic=lambda:10.)
    first=engine.infer(observation())
    second=engine.infer(observation(sequence=11,rgb=b'\x00'*192))
    assert first.consumed_current and not second.consumed_current
    assert first.source==second.source and second.chunk_index==1
    (root/'policy/model.safetensors').write_bytes(b'corrupt after immutable load')
    engine.reset('episode_change')
    replayed=engine.infer(observation())
    torch.testing.assert_close(torch.tensor(first.positions),torch.tensor(replayed.positions),rtol=0,atol=0)
    with pytest.raises(ValueError):ACTInference(root,doc['revision'])


def test_replay_requires_new_output_and_pinned_revision(tmp_path):
    from act_inference_replay import replay
    out=tmp_path/'exists';out.mkdir()
    with pytest.raises(ValueError,match='new artifact'):
        replay(tmp_path,tmp_path,out,'a'*64)
