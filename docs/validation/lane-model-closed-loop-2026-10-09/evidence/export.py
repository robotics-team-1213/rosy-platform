import argparse, hashlib, json
from pathlib import Path
import cv2, numpy as np, torch

p=argparse.ArgumentParser()
p.add_argument('--architecture',choices=['pidnet','unet'],required=True)
p.add_argument('--root',type=Path,required=True)
p.add_argument('--frames',type=Path,required=True)
p.add_argument('--out',type=Path,required=True)
a=p.parse_args()
assert not a.out.exists()
a.out.mkdir(parents=True)
ck=a.root/'runs'/a.architecture/'best.pt'
if a.architecture=='pidnet':
 from pinky_pidnet.model import load_checkpoint
 model,_=load_checkpoint(ck,torch.device('cpu'))
else:
 from pinky_lane.checkpoints import load_model
 model,_,_,_=load_model(ck,'cpu',ignore_top=0)
model.eval()
example=torch.zeros((1,3,240,320),dtype=torch.float32)
with torch.inference_mode():
 out=model(example)
assert tuple(out.shape)==(1,5,240,320), tuple(out.shape)
torch.onnx.export(model,example,str(a.out/'model.onnx'),input_names=['image'],output_names=['logits'],opset_version=17,dynamo=False)
frames=np.load(a.frames)['frames']
indices=[0,100,250,400,543]
assert len(frames)==544
inputs=np.stack([cv2.cvtColor(frames[i],cv2.COLOR_BGR2RGB).astype(np.float32).transpose(2,0,1)/255 for i in indices])
with torch.inference_mode():
 logits=model(torch.from_numpy(inputs)).numpy()
np.savez_compressed(a.out/'parity.npz',inputs=inputs,logits=logits)
report={'architecture':a.architecture,'checkpoint_sha256':hashlib.sha256(ck.read_bytes()).hexdigest(),
 'onnx_sha256':hashlib.sha256((a.out/'model.onnx').read_bytes()).hexdigest(),
 'input_shape':[1,3,240,320],'output_shape':[1,5,240,320],'opset':17,'parity_indices':indices,
 'source_sha256':hashlib.sha256(a.frames.read_bytes()).hexdigest()}
(a.out/'export.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report),flush=True)
