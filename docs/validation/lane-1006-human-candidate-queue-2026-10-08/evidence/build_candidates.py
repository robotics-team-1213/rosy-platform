from pathlib import Path
from hashlib import sha256
import csv, json, subprocess
from PIL import Image

source=Path('X:/DevTemp/projects/rosy-platform/2026-10-08--045427--lane-evidence-learning--e0687b/evidence/recordings/video')
out=Path('X:/DevTemp/rosy-lane-1006-review-candidates-20261008')
frames_dir=out/'frames';frames_dir.mkdir(parents=True,exist_ok=True)
plans={
 '082612':[(188,211),(876,892),(2118,2140),(2448,2463),(2464,2486)],
 '091340':[(180,202),(387,410),(440,450),(625,641)],
}
expected={
 '082612':{'frames':2487,'video_sha256':'e6c3785b4cbc0cbd8f81ce4b09b1202ec4c15792981ee803628becef5949dd13','sidecar_sha256':'767c05c7781e0f0cad3c827eb21e1c3f800588e0f2500fe6fb7dcbdde9896d65'},
 '091340':{'frames':642,'video_sha256':'cb4eb6d39c24a6a0cc4ad5adee615b0e21ef2ef781f6b8d68aa89fe9fff3c491','sidecar_sha256':'eec1f44a8c658749cac35cd72a990dc0979d44e0ff8c5fa8f331bea776ec141d'},
}
fields=['source_session','frame_index','header_stamp_ns','video_sha256','image','image_sha256','same_lane_pair','boundary_id_left','boundary_id_right','loss_cause','reappearance_frame','visible_drivable','reviewer','reviewed_at','notes']
rows=[]
for prefix,windows in plans.items():
    cfg=expected[prefix]
    video=source/f'teleop_rosy_26_20261006T{prefix}Z.mp4'
    sidecar=source/f'teleop_rosy_26_20261006T{prefix}Z.jsonl'
    assert sha256(video.read_bytes()).hexdigest()==cfg['video_sha256']
    assert sha256(sidecar.read_bytes()).hexdigest()==cfg['sidecar_sha256']
    sides=[json.loads(s) for s in sidecar.read_text(encoding='utf-8').splitlines()]
    assert len(sides)==cfg['frames']
    selected={i for a,b in windows for i in range(a,b+1)}
    assert len(selected)==sum(b-a+1 for a,b in windows)
    p=subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','error','-i',str(video),'-f','rawvideo','-pix_fmt','rgb24','-vsync','0','-'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    for index,meta in enumerate(sides):
        raw=p.stdout.read(320*240*3)
        assert len(raw)==320*240*3,(prefix,index,len(raw))
        assert meta['index']==index and isinstance(meta['stamp_ns'],int)
        if index not in selected:continue
        image=frames_dir/f'{prefix}_{index:06}.png'
        Image.frombytes('RGB',(320,240),raw).save(image)
        rows.append({'source_session':f'20261006T{prefix}Z_rosy_26','frame_index':index,'header_stamp_ns':meta['stamp_ns'],'video_sha256':cfg['video_sha256'],'image':f'frames/{image.name}','image_sha256':sha256(image.read_bytes()).hexdigest(),**{name:'' for name in fields[6:]}})
    assert p.stdout.read(1)==b'',prefix
    err=p.stderr.read().decode('utf-8',errors='replace')
    assert p.wait()==0,(prefix,err)
    print(prefix,len(selected),flush=True)
assert len(rows)==sum(b-a+1 for ws in plans.values() for a,b in ws)
queue=out/'candidate-review-queue.csv'
with queue.open('w',encoding='utf-8',newline='') as f:
    w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
html=['<!doctype html><meta charset="utf-8"><title>10/6 raw candidate frames</title>','<style>body{font:16px system-ui;max-width:1000px;margin:2rem auto}section{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:1rem}figure{margin:0}img{width:320px;height:240px}figcaption{font-size:13px}</style>','<h1>10/6 원본 후보 프레임</h1><p>검수 정답 아님. 모델 출력 없음. 프레임 전후는 원본 MP4에서 확인.</p>']
for prefix,windows in plans.items():
    for a,b in windows:
        html.append(f'<h2>{prefix} · {a}–{b}</h2><section>')
        for row in rows:
            if row['source_session'].startswith(f'20261006T{prefix}') and a<=row['frame_index']<=b:
                html.append(f'<figure><img src="{row["image"]}" loading="lazy"><figcaption>{row["frame_index"]} · {row["header_stamp_ns"]}</figcaption></figure>')
        html.append('</section>')
gallery=out/'candidate-gallery.html';gallery.write_text('\n'.join(html),encoding='utf-8')
receipt={'schema':'rosy.lane-candidate-review-queue/1','status':'candidate_only_not_human_truth','source_kind':'mp4_derivative_from_verified_mcap','sessions':{f'20261006T{k}Z_rosy_26':{'frames':expected[k]['frames'],'selected':sum(b-a+1 for a,b in v),'video_sha256':expected[k]['video_sha256'],'sidecar_sha256':expected[k]['sidecar_sha256'],'windows':v} for k,v in plans.items()},'rows':len(rows),'queue_sha256':sha256(queue.read_bytes()).hexdigest(),'gallery_sha256':sha256(gallery.read_bytes()).hexdigest(),'human_approved_events':0,'lane_follow_acceptance':False}
(out/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(receipt,ensure_ascii=False,indent=2))
