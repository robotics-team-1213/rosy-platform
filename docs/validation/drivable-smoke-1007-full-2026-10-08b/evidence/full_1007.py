from pathlib import Path
from hashlib import sha256
from collections import Counter
import json
import numpy as np
import onnxruntime as ort
from PIL import Image

scratch=Path('X:/DevTemp/rosy-drivable-candidate-20261008')
evidence=Path('X:/DevTemp/projects/rosy-platform/2026-10-08--045427--lane-evidence-learning--e0687b/evidence')
manifest=json.loads((scratch/'model_manifest.json').read_text(encoding='utf-8'))
assert sha256((scratch/'model.onnx').read_bytes()).hexdigest()==manifest['files'][0]['sha256']
session=ort.InferenceSession(str(scratch/'model.onnx'),providers=['CPUExecutionProvider'])
input_name=session.get_inputs()[0].name
records=[]
for prefix,folder,count in [('143038','replay-1007-143038',124),('143211','replay-1007-143211',83)]:
    replay=[json.loads(s) for s in (evidence/folder/'frames.jsonl').read_text(encoding='utf-8').splitlines()]
    frames=sorted((scratch/'full-1007'/prefix).glob('*.png'))
    assert len(replay)==len(frames)==count,(prefix,len(replay),len(frames))
    prev=None
    for idx,(path,state) in enumerate(zip(frames,replay)):
        assert path.stem==f'{idx+1:06}'
        rgb=np.asarray(Image.open(path).convert('RGB'))
        assert rgb.shape==(240,320,3)
        x=np.ascontiguousarray((rgb.astype(np.float32)*np.float32(manifest['input']['scale'])).transpose(2,0,1)[None])
        logits=session.run(None,{input_name:x})[0]
        assert logits.shape==(1,6,240,320) and np.isfinite(logits).all()
        labels=logits[0].argmax(axis=0)
        mask=labels[144:]==5
        xs=np.nonzero(mask)[1]
        overlap=None if prev is None else float(np.logical_and(prev,mask).sum()/max(1,np.logical_or(prev,mask).sum()))
        records.append({'session':prefix,'frame':idx,'t':state['t'],'level':state['level'],'boundary_tier':state['boundary_tier'],'near_drivable_fraction':float(mask.mean()),'near_drivable_center_x':float(xs.mean()) if len(xs) else None,'adjacent_raw_iou':overlap})
        prev=mask
out=scratch/'full-1007'
with (out/'per_frame.jsonl').open('w',encoding='utf-8') as f:
    for row in records:f.write(json.dumps(row,ensure_ascii=False)+'\n')
summary={'status':'candidate_proxy_not_ground_truth','model_revision':manifest['model_revision'],'model_sha256':manifest['files'][0]['sha256'],'frames':len(records),'sessions':{}}
for prefix in ('143038','143211'):
    rs=[r for r in records if r['session']==prefix]
    fr=np.asarray([r['near_drivable_fraction'] for r in rs])
    overlaps=np.asarray([r['adjacent_raw_iou'] for r in rs[1:]])
    stop=[r for r in rs if r['level']=='STOP']
    summary['sessions'][prefix]={'frames':len(rs),'level_counts':dict(Counter(r['level'] for r in rs)),'boundary_tier_counts':dict(Counter(r['boundary_tier'] for r in rs)),'near_drivable_fraction':{'min':float(fr.min()),'median':float(np.median(fr)),'max':float(fr.max())},'stop_frames_with_near_drivable_over_half':sum(r['near_drivable_fraction']>.5 for r in stop),'stop_frames':len(stop),'adjacent_raw_iou':{'min':float(overlaps.min()),'median':float(np.median(overlaps))},'frames_below_two_percent':int((fr<.02).sum())}
(out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
