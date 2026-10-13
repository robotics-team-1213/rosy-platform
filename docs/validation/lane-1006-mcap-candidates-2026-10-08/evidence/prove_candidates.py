"""Bind diagnostic review frames to original MCAP camera messages; no labels."""
import csv
import hashlib
import html
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / 'learning/training/perception/dataset'))
from mcap_proof import prove_frames

ROOT = Path('X:/DevTemp/rosy-lane-1006-mcap-review-20261008')
VIDEO = Path('X:/DevTemp/rosy-lane-1006-review-candidates-20261008')
RECORDINGS = Path('X:/DevTemp/projects/rosy-platform/2026-10-08--045427--lane-evidence-learning--e0687b/evidence/recordings')
TOPIC = '/rosy_26/camera/front/compressed'
HUMAN = ['same_lane_pair', 'boundary_id_left', 'boundary_id_right', 'loss_cause',
         'reappearance_frame', 'visible_drivable', 'reviewer', 'reviewed_at', 'notes']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


old = list(csv.DictReader((VIDEO / 'candidate-review-queue.csv').open(encoding='utf-8', newline='')))
source = json.loads((RECORDINGS / 'source-readback-1006.json').read_text(encoding='utf-8'))
new, proofs = [], {}
for session in source['sessions']:
    sid = session['id']
    prefix = sid[9:15]
    selected = [r for r in old if r['source_session'] == sid]
    if not selected:
        continue
    session_path = RECORDINGS / sid
    extracted = [json.loads(line) for line in (ROOT / prefix / 'frames.jsonl').read_text(encoding='utf-8').splitlines()]
    sidecar = [json.loads(line) for line in (RECORDINGS / 'video' / f'teleop_rosy_26_20261006T{prefix}Z.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(extracted) == len(sidecar), sid
    assert all(a['index'] == b['index'] == i and a['stamp_ns'] == b['stamp_ns']
               and a['log_ns'] == b['log_ns'] for i, (a, b) in enumerate(zip(extracted, sidecar))), sid
    wanted = []
    for row in selected:
        index = int(row['frame_index'])
        meta = extracted[index]
        assert meta['stamp_ns'] == int(row['header_stamp_ns']), (sid, index)
        image = ROOT / prefix / 'frames' / f'{index:06d}.jpg'
        assert image.is_file(), image
        wanted.append({'topic': TOPIC, 'log_ns': meta['log_ns'], 'image': str(image),
                       'header_stamp_ns': meta['stamp_ns']})
    expected = {
        'metadata_sha256': next(f['sha256'] for f in session['files'] if f['path'] == 'bag/metadata.yaml'),
        'bags': [{'name': f['path'].split('/')[-1], 'sha256': f['sha256']}
                 for f in sorted((f for f in session['files'] if f['path'].endswith('.mcap')),
                                 key=lambda f: int(f['path'].split('_')[-1].split('.')[0]))],
    }
    proof = prove_frames(session_path, wanted, ROOT, expected=expected)
    assert len(proof['frames']) == len(selected)
    proof_path = ROOT / f'proof-{prefix}.json'
    proof_path.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')
    proofs[sid] = {'frames': len(extracted), 'selected': len(selected),
                   'proof_sha256': digest(proof_path), 'source_metadata_sha256': expected['metadata_sha256']}
    by_stamp = {f['header_stamp_ns']: f for f in proof['frames']}
    assert len(by_stamp) == len(proof['frames'])
    for row in selected:
        index = int(row['frame_index'])
        stamped = int(row['header_stamp_ns'])
        proved = by_stamp[stamped]
        new.append({'source_session': sid, 'frame_index': index, 'header_stamp_ns': stamped,
                    'log_ns': proved['log_ns'], 'source_kind': 'mcap',
                    'bag': proved['bag'], 'channel_id': proved['channel_id'],
                    'message_ordinal': proved['message_ordinal'],
                    'image': f'{prefix}/frames/{index:06d}.jpg',
                    'image_sha256': proved['image_sha256'],
                    **{name: '' for name in HUMAN}})

assert len(new) == len(old) == 178
fields = list(new[0])
queue = ROOT / 'mcap-candidate-review-queue.csv'
with queue.open('w', encoding='utf-8', newline='') as handle:
    writer = csv.DictWriter(handle, fieldnames=fields)
    writer.writeheader()
    writer.writerows(new)
gallery = ROOT / 'mcap-candidate-gallery.html'
page = ['<!doctype html><meta charset="utf-8"><title>10/6 MCAP candidate frames</title>',
        '<style>body{font:16px system-ui;max-width:1000px;margin:2rem auto}section{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:1rem}figure{margin:0}img{width:320px;height:240px}figcaption{font-size:13px}</style>',
        '<h1>10/6 MCAP 원본 후보 프레임</h1><p>사람 검수 정답 아님. 모델 출력 없음. 기존 모델 진단으로 일부 구간을 선택했으므로 고정 평가 세트가 아님.</p>']
previous = None
for row in new:
    if row['source_session'] != previous:
        if previous is not None:
            page.append('</section>')
        page.append(f'<h2>{html.escape(row["source_session"])}</h2><section>')
        previous = row['source_session']
    page.append(f'<figure><img src="{row["image"]}" loading="lazy"><figcaption>{row["frame_index"]} · {row["header_stamp_ns"]}</figcaption></figure>')
page.append('</section>')
gallery.write_text('\n'.join(page), encoding='utf-8')
receipt = {'schema': 'rosy.mcap-candidate-review/1', 'status': 'candidate_only_not_human_truth',
           'source_kind': 'mcap', 'source_readback_sha256': digest(RECORDINGS / 'source-readback-1006.json'),
           'video_candidate_queue_sha256': digest(VIDEO / 'candidate-review-queue.csv'),
           'sessions': proofs, 'rows': len(new), 'human_approved_events': 0,
           'queue_sha256': digest(queue), 'gallery_sha256': digest(gallery)}
(ROOT / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(receipt, ensure_ascii=False, indent=2))
