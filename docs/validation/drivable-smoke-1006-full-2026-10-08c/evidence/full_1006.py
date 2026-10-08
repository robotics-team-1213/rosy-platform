from pathlib import Path
from hashlib import sha256
from collections import Counter,defaultdict
import json, subprocess
import numpy as np
import onnxruntime as ort

scratch=Path('X:/DevTemp/rosy-drivable-candidate-20261008')
evidence=Path('X:/DevTemp/projects/rosy-platform/2026-10-08--045427--lane-evidence-learning--e0687b/evidence')
video_dir=evidence/'recordings'/'video'
manifest=json.loads((scratch/'model_manifest.json').read_text(encoding='utf-8'))
assert sha256((scratch/'model.onnx').read_bytes()).hexdigest()==manifest['files'][0]['sha256']
assert manifest['input']['shape']==[1,3,240,320] and manifest['input']['color']=='rgb'
assert not any(c['role']=='wall' for c in manifest['output']['classes'])
opts=ort.SessionOptions(); opts.intra_op_num_threads=2
session=ort.InferenceSession(str(scratch/'model.onnx'),sess_options=opts,providers=['CPUExecutionProvider'])
input_name=session.get_inputs()[0].name
expected={'082612':('e6c3785b4cbc0cbd8f81ce4b09b1202ec4c15792981ee803628becef5949dd13',2487),'091340':('cb4eb6d39c24a6a0cc4ad5adee615b0e21ef2ef781f6b8d68aa89fe9fff3c491',642)}
rows=[]
for prefix,(want_hash,want_count) in expected.items():
    video=video_dir/f'teleop_rosy_26_20261006T{prefix}Z.mp4'
    sidecar=video_dir/f'teleop_rosy_26_20261006T{prefix}Z.jsonl'
    assert sha256(video.read_bytes()).hexdigest()==want_hash
    sides=[json.loads(line) for line in sidecar.read_text(encoding='utf-8').splitlines()]
    assert len(sides)==want_count
    proc=subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','error','-i',str(video),'-f','rawvideo','-pix_fmt','rgb24','-vsync','0','-'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    prev=None
    for index,side in enumerate(sides):
        assert side['index']==index and side['side']['line/keep_debug'] is not None
        frame=proc.stdout.read(320*240*3)
        assert len(frame)==320*240*3,(prefix,index,len(frame))
        rgb=np.frombuffer(frame,dtype=np.uint8).reshape(240,320,3)
        x=np.ascontiguousarray((rgb.astype(np.float32)*np.float32(manifest['input']['scale'])).transpose(2,0,1)[None])
        logits=session.run(None,{input_name:x})[0]
        assert logits.shape==(1,6,240,320) and np.isfinite(logits).all()
        labels=logits[0].argmax(axis=0)
        mask=labels[144:]==5
        overlap=None if prev is None else float(np.logical_and(prev,mask).sum()/max(1,np.logical_or(prev,mask).sum()))
        xs=np.nonzero(mask)[1]
        rows.append({'session':prefix,'frame':index,'stamp_ns':side['stamp_ns'],'keeper_strategy':side['side']['line/keep_debug']['strategy'],'moving':bool(side['motion']['moving']),'near_drivable_fraction':float(mask.mean()),'near_drivable_center_x':float(xs.mean()) if len(xs) else None,'adjacent_raw_iou':overlap})
        prev=mask
        if (index+1)%500==0:print(prefix,index+1,flush=True)
    assert proc.stdout.read(1)==b'',(prefix,'extra frame bytes')
    err=proc.stderr.read().decode('utf-8',errors='replace')
    assert proc.wait()==0,(prefix,err)
    print(prefix,'complete',want_count,flush=True)
out=scratch/'full-1006';out.mkdir(exist_ok=True)
with (out/'per_frame.jsonl').open('w',encoding='utf-8') as f:
    for row in rows:f.write(json.dumps(row,ensure_ascii=False)+'\n')
summary={'status':'candidate_proxy_not_ground_truth','model_revision':manifest['model_revision'],'model_sha256':manifest['files'][0]['sha256'],'frames':len(rows),'sessions':{}}
for prefix,(_,count) in expected.items():
    rs=[r for r in rows if r['session']==prefix]
    assert len(rs)==count
    fr=np.asarray([r['near_drivable_fraction'] for r in rs])
    overlaps=np.asarray([r['adjacent_raw_iou'] for r in rs[1:]])
    groups={}
    for strategy in sorted(set(r['keeper_strategy'] for r in rs)):
        items=[r for r in rs if r['keeper_strategy']==strategy]
        groups[strategy]={'frames':len(items),'over_half':sum(r['near_drivable_fraction']>.5 for r in items),'median_fraction':float(np.median([r['near_drivable_fraction'] for r in items]))}
    moved=[r for r in rs if r['moving']]
    summary['sessions'][prefix]={'frames':len(rs),'keeper_strategy':dict(Counter(r['keeper_strategy'] for r in rs)),'moving_frames':len(moved),'fraction':{'min':float(fr.min()),'median':float(np.median(fr)),'max':float(fr.max())},'over_half':int((fr>.5).sum()),'below_two_percent':int((fr<.02).sum()),'adjacent_raw_iou':{'min':float(overlaps.min()),'median':float(np.median(overlaps))},'by_keeper_strategy':groups,'moving_none_over_half':sum(r['keeper_strategy']=='none' and r['near_drivable_fraction']>.5 for r in moved),'moving_none':sum(r['keeper_strategy']=='none' for r in moved)}
(out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
