"""Build an offline object review editor; masks remain a separate CVAT task.

Usage: review_pack.py <existing-review-dir> --out <new-dir>
Original JPEG bytes are verified and copied unchanged. No human approval is inferred.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path

CLASSES = ('robot', 'obstacle_box', 'cone', 'traffic_light', 'sign', 'person_feet')


def _rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def _image(root, name, digest):
    if not isinstance(name, str) or '..' in Path(name).parts or Path(name).drive:
        raise ValueError('image must stay within source root')
    path = (root / name).resolve()
    if Path(name).is_absolute() or not path.is_relative_to(root.resolve()):
        raise ValueError('image must stay within source root')
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError('image hash mismatch')
    import cv2
    import numpy as np
    decoded = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if decoded is None:
        raise ValueError('image cannot be decoded')
    return data, decoded.shape[1], decoded.shape[0]


def build_review(source, out):
    source, out = Path(source).resolve(), Path(out)
    objects, gallery = [], []
    copied = []
    for index, row in enumerate(_rows(source / 'object-drafts.jsonl')):
        data, width, height = _image(source, row['image'], row['image_sha256'])
        bound = dict(row, index=index, width=width, height=height,
                     review_status='pending_human', complete_frame_review=False)
        bound['boxes'] = [dict(box, **({'signal_state': box.get('signal_state', 'unknown')}
                                      if box['label'] == 'traffic_light' else {})) for box in row['boxes']]
        objects.append(dict(bound, data_url='data:image/jpeg;base64,' + base64.b64encode(data).decode()))
        copied.append((row['image'], data))
    for row in _rows(source / 'frames.jsonl'):
        name = f"frames/{row['index']:06d}.jpg"
        data, width, height = _image(source, name, row['image_sha256'])
        if (width, height) != (row['width'], row['height']):
            raise ValueError('frame dimensions mismatch')
        gallery.append(dict(row, data_url='data:image/jpeg;base64,' + base64.b64encode(data).decode()))
    payload = json.dumps({'objects': objects, 'gallery': gallery, 'classes': CLASSES}, ensure_ascii=False)
    # Prevent source metadata from terminating an inline script.
    page = PAGE.replace('__PAYLOAD__', payload.replace('<', '\\u003c'))
    out.mkdir(parents=True, exist_ok=False)
    for name, data in copied:
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    bound_rows = [{k: v for k, v in row.items() if k != 'data_url'} for row in objects]
    (out / 'object-source.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n'
                                                   for row in bound_rows), encoding='utf-8')
    (out / 'review.html').write_text(page, encoding='utf-8')
    summary = {'object_frames': len(objects), 'draft_boxes': sum(len(r['boxes']) for r in objects),
               'segmentation_frames': len(gallery), 'verified_original_images': len(objects) + len(gallery),
               'human_approved_frames': 0, 'mask_editor': False}
    (out / 'verification.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    return summary


PAGE = r'''<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ROSY 영상 라벨 검수</title>
<style>body{font:16px system-ui;margin:24px;background:#f5f5f3;color:#202520}button,select,textarea{font:inherit;padding:8px;margin:4px}button{cursor:pointer}main{max-width:1100px;margin:auto}.workspace{display:flex;gap:20px;flex-wrap:wrap}canvas{width:100%;max-width:720px;touch-action:none;border:1px solid #555;background:#ddd}.image{flex:2;min-width:300px}.controls{flex:1;min-width:260px}textarea{box-sizing:border-box;width:100%;height:190px}#gallery{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px}#gallery img{width:100%}.card{background:white;padding:12px}#status{font-weight:bold}label{display:block;margin:12px 0}small{overflow-wrap:anywhere}li{cursor:pointer;padding:6px}li.selected{background:#d5eadd}</style>
<main><h1>촬영 영상 라벨 검수</h1><p>객체 4프레임: 박스를 선택한 뒤 다시 드래그하면 위치·크기가 바뀝니다. 새 박스 버튼을 누른 뒤 드래그하면 추가됩니다. 원본 이미지의 픽셀은 변경하지 않습니다.</p>
<p><strong>변경은 다운로드 전까지 이 브라우저에만 있습니다. 새로고침하거나 탭을 닫으면 저장하지 않은 수정이 사라집니다.</strong> 아래에서 프레임 전체를 확인하고 승인해야 학습 라벨 후보로 표시됩니다. 이 파일은 검수자 신원을 인증하지 않습니다.</p>
<button id="prev">이전 프레임</button><button id="next">다음 프레임</button><span id="position"></span>
<p id="source"></p><small id="digest"></small><div class="workspace"><div class="image"><canvas id="canvas"></canvas></div><div class="controls">
<p id="status"></p><button id="new">새 박스</button><button id="delete">선택 박스 삭제</button>
<label>클래스 <select id="class"></select></label><label>신호 상태 <select id="signal"><option>unknown</option><option>red</option><option>yellow</option><option>green</option><option>off</option></select></label>
<ul id="boxes"></ul><label><input type="checkbox" id="complete"> 화면 전체의 객체와 누락을 확인했습니다</label><button id="approve">현재 프레임 승인</button>
<details><summary>박스 JSON 직접 편집</summary><textarea id="json" aria-label="박스 JSON"></textarea><button id="apply">JSON 적용</button></details><p id="error" role="alert"></p></div></div>
<button id="download">검수 JSONL 다운로드</button><details><summary>다운로드가 막힐 때 JSONL 복사</summary><button id="showexport">현재 검수 JSONL 표시</button><textarea id="exporttext" readonly aria-label="검수 JSONL 복사"></textarea><p>내용 전체를 복사해 UTF-8 human-review.jsonl 파일로 저장하세요.</p></details><p>다운로드한 <code>human-review.jsonl</code>을 원본 바인딩 <code>object-source.jsonl</code>과 함께 전달하세요. 검수 후에도 데이터 분할·평가·모델 승격은 별도 단계입니다.</p>
<details><summary>분할 라벨용 76프레임 보기 · 객체 검수와 별도</summary><p>벽·바닥·차선·주행 가능 영역·정지선은 CVAT에서 픽셀 마스크로 검수합니다. 불확실한 픽셀은 ignore=255로 두세요. 이 페이지는 분할 마스크를 편집하거나 승인하지 않습니다. 기존 lane-drafts와 classes.yaml을 사용하고 촬영 그룹별 학습/평가 분할을 유지하세요.</p><div id="gallery"></div></details></main>
<script>
const pack=__PAYLOAD__;let current=0,selected=-1,start=null,image=new Image(),loading=true,loadToken=0;
const rows=pack.objects.map(r=>({...r,boxes:structuredClone(r.boxes),review_status:'pending_human',complete_frame_review:false}));
const $=id=>document.getElementById(id),canvas=$('canvas'),ctx=canvas.getContext('2d');
// Capturing listener also prevents stale list selections during image loading.
document.addEventListener('click',e=>{if(loading&&(e.target.closest('#boxes')||['new','delete','approve','apply'].includes(e.target.id))){e.preventDefault();e.stopImmediatePropagation()}},true);
pack.classes.forEach(c=>{let o=document.createElement('option');o.value=c;o.textContent=c;$('class').append(o)});
function row(){return rows[current]}function invalidate(){row().review_status='pending_human';row().complete_frame_review=false; $('complete').checked=false}
function validate(boxes){if(!Array.isArray(boxes))throw Error('boxes는 배열이어야 합니다');for(const b of boxes){let a=b.bbox_xyxy;if(!pack.classes.includes(b.label)||!Array.isArray(a)||a.length!==4||!a.every(Number.isFinite)||a[0]<0||a[1]<0||a[2]>row().width||a[3]>row().height||a[0]>=a[2]||a[1]>=a[3])throw Error('클래스 또는 박스 좌표를 확인하세요');if(b.label==='traffic_light'){b.signal_state=b.signal_state||'unknown';if(!['unknown','red','yellow','green','off'].includes(b.signal_state))throw Error('신호 상태를 확인하세요')}}}
function draw(){ctx.clearRect(0,0,canvas.width,canvas.height);ctx.drawImage(image,0,0);row().boxes.forEach((b,i)=>{let a=b.bbox_xyxy;ctx.strokeStyle=i===selected?'#00ff99':'#ffcc00';ctx.lineWidth=2;ctx.strokeRect(a[0],a[1],a[2]-a[0],a[3]-a[1]);ctx.fillStyle='#000';ctx.fillRect(a[0],Math.max(0,a[1]-15),100,15);ctx.fillStyle='white';ctx.font='11px sans-serif';ctx.fillText(i+': '+b.label,a[0]+2,Math.max(12,a[1]-3))})}
function refresh(){let r=row();$('position').textContent=(current+1)+' / '+rows.length;$('source').textContent=r.video+' · 원본 프레임 '+r.video_frame;$('digest').textContent='SHA256 '+r.image_sha256;$('status').textContent=r.review_status==='approved'?'이 프레임 승인됨':'검수 대기';$('complete').checked=r.complete_frame_review;$('json').value=JSON.stringify(r.boxes,null,2);$('boxes').replaceChildren();r.boxes.forEach((b,i)=>{let li=document.createElement('li');li.textContent=i+': '+b.label+' '+b.bbox_xyxy.join(', ');li.className=i===selected?'selected':'';li.onclick=()=>{selected=i;refresh()};$('boxes').append(li)});if(selected>=0){$('class').value=r.boxes[selected].label;$('signal').value=r.boxes[selected].signal_state||'unknown'}$('signal').disabled=selected<0||r.boxes[selected].label!=='traffic_light';draw()}
function setLoading(value){loading=value;['new','delete','class','signal','complete','approve','apply'].forEach(id=>$(id).disabled=value)}
function load(){selected=-1;start=null;const token=++loadToken;setLoading(true);canvas.width=row().width;canvas.height=row().height;ctx.clearRect(0,0,canvas.width,canvas.height);$('status').textContent='원본 이미지 로딩 중 · 검수 잠김';$('error').textContent='';const pending=new Image();pending.onload=()=>{if(token!==loadToken)return;image=pending;setLoading(false);refresh()};pending.onerror=()=>{if(token===loadToken){setLoading(true);$('error').textContent='원본 이미지 로딩 실패 · 검수할 수 없습니다'}};pending.src=row().data_url}
function point(e){let b=canvas.getBoundingClientRect();return [Math.max(0,Math.min(canvas.width,(e.clientX-b.left)*canvas.width/b.width)),Math.max(0,Math.min(canvas.height,(e.clientY-b.top)*canvas.height/b.height))].map(Math.round)}
canvas.onpointerdown=e=>{if(loading)return;start=point(e);canvas.setPointerCapture(e.pointerId)};
canvas.onpointerup=e=>{if(!start)return;let end=point(e),a=[Math.min(start[0],end[0]),Math.min(start[1],end[1]),Math.max(start[0],end[0]),Math.max(start[1],end[1])];start=null;if(a[2]-a[0]<2||a[3]-a[1]<2){selected=row().boxes.findIndex(b=>a[0]>=b.bbox_xyxy[0]&&a[0]<=b.bbox_xyxy[2]&&a[1]>=b.bbox_xyxy[1]&&a[1]<=b.bbox_xyxy[3]);refresh();return}let b={label:$('class').value,bbox_xyxy:a};if(b.label==='traffic_light')b.signal_state=$('signal').value;if(selected<0){row().boxes.push(b);selected=row().boxes.length-1}else row().boxes[selected]=b;invalidate();refresh()};
$('new').onclick=()=>{selected=-1;refresh()};$('delete').onclick=()=>{if(selected<0)return;row().boxes.splice(selected,1);selected=-1;invalidate();refresh()};
$('class').onchange=()=>{if(selected<0)return;row().boxes[selected].label=$('class').value;if($('class').value==='traffic_light')row().boxes[selected].signal_state='unknown';else delete row().boxes[selected].signal_state;invalidate();refresh()};
$('signal').onchange=()=>{if(selected>=0&&row().boxes[selected].label==='traffic_light'){row().boxes[selected].signal_state=$('signal').value;invalidate();refresh()}};
$('apply').onclick=()=>{if(loading)return;try{let b=JSON.parse($('json').value);validate(b);row().boxes=b;selected=-1;invalidate();$('error').textContent='';refresh()}catch(e){$('error').textContent=e.message}};
$('complete').onchange=()=>{if(loading)return;row().complete_frame_review=$('complete').checked;row().review_status='pending_human';refresh()};
$('approve').onclick=()=>{if(loading)return;try{validate(row().boxes);if(!row().complete_frame_review)throw Error('먼저 화면 전체 확인을 체크하세요');row().review_status='approved';$('error').textContent='';refresh()}catch(e){$('error').textContent=e.message}};
$('prev').onclick=()=>{current=Math.max(0,current-1);load()};$('next').onclick=()=>{current=Math.min(rows.length-1,current+1);load()};
function exportRows(){return rows.map(r=>({index:r.index,image_sha256:r.image_sha256,video:r.video,video_frame:r.video_frame,review_status:r.review_status,complete_frame_review:r.complete_frame_review,boxes:structuredClone(r.boxes)}))}
$('showexport').onclick=()=>{$('exporttext').value=exportRows().map(r=>JSON.stringify(r)).join('\n')+'\n'};
$('download').onclick=()=>{let data=exportRows().map(r=>JSON.stringify(r)).join('\n')+'\n';let a=document.createElement('a');let url=URL.createObjectURL(new Blob([data],{type:'application/x-ndjson'}));a.href=url;a.download='human-review.jsonl';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
pack.gallery.forEach(r=>{let div=document.createElement('div');div.className='card';let im=document.createElement('img');im.src=r.data_url;im.loading='lazy';let p=document.createElement('p');p.textContent=r.index+' · '+r.session+' · '+r.video_frame+' · '+r.proposed_split;div.append(im,p);$('gallery').append(div)});load();
</script></html>'''


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_review(args.source, args.out)))
