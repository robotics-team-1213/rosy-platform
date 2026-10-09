import argparse, hashlib, json
from pathlib import Path
import numpy as np, onnxruntime as ort

p=argparse.ArgumentParser()
p.add_argument('folder',type=Path)
p.add_argument('--checkpoint-sha',required=True)
a=p.parse_args()
model=a.folder/'model.onnx'
source=np.load(a.folder/'parity.npz')
inputs=source['inputs']; expected=source['logits']
assert inputs.shape==(5,3,240,320) and expected.shape==(5,5,240,320)
s=ort.InferenceSession(str(model),providers=['CPUExecutionProvider'])
name=s.get_inputs()[0].name
actual=np.concatenate([s.run(None,{name:x[None]})[0] for x in inputs])
assert actual.shape==expected.shape and np.isfinite(actual).all()
diff=float(np.max(np.abs(actual-expected)))
mismatch=int(np.count_nonzero(actual.argmax(1)!=expected.argmax(1)))
report={'onnx_sha256':hashlib.sha256(model.read_bytes()).hexdigest(),'parity_max_abs_diff':diff,'argmax_mismatch_pixels':mismatch,'tested_pixels':int(np.prod(expected.shape[:1])*np.prod(expected.shape[2:]))}
(a.folder/'parity_report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report),flush=True)
assert mismatch==0 and diff<0.001, 'export parity failed'
base=json.loads((Path.home()/'rosy-ml/scratch/v11-robot-20261006/intake/lane-seg-20261006-5f5ddcd9/model_manifest.json').read_text())
base['model_revision']='sim-'+a.folder.name+'-'+report['onnx_sha256'][:8]
base['files'][0]['sha256']=report['onnx_sha256']
base['dataset']={'repo':'ai-pc-pinky-v13-pidnet-unet-20261008','revision':a.checkpoint_sha}
base['metrics']={'export_parity_max_abs_diff':diff,'argmax_mismatch_pixels':mismatch,'export_kind':'torch-onnx-opset17'}
base['trainer']='pinky-v13-candidate'
(a.folder/'model_manifest.json').write_text(json.dumps(base,indent=2)+'\n')
