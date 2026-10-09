from pathlib import Path
from hashlib import sha256
import json
import numpy as np
import onnxruntime as ort
from PIL import Image, ImageDraw

root = Path('X:/DevTemp/rosy-drivable-candidate-20261008')
source = Path('X:/DevTemp/projects/rosy-platform/2026-10-08--045427--lane-evidence-learning--e0687b/evidence/human-review-candidates')
manifest = json.loads((root / 'model_manifest.json').read_text(encoding='utf-8'))
model = root / 'model.onnx'
assert sha256(model.read_bytes()).hexdigest() == manifest['files'][0]['sha256']
assert manifest['input']['shape'] == [1, 3, 240, 320]
assert manifest['input']['color'] == 'rgb'
assert manifest['output']['classes'][5]['name'] == 'drivable'
session = ort.InferenceSession(str(model), providers=['CPUExecutionProvider'])
name = session.get_inputs()[0].name
out = root / 'candidate-output'
out.mkdir(exist_ok=True)
frames = ['20261007T143038Z_000.png', '20261007T143038Z_020.png', '20261007T143038Z_035.png', '20261007T143038Z_080.png', '20261007T143038Z_123.png', '20261007T143211Z_055.png', '20261006T091340Z_190.png', '20261006T091340Z_448.png']
rows = []
for filename in frames:
    path = source / filename
    im = Image.open(path).convert('RGB')
    assert im.size == (320, 240), (filename, im.size)
    rgb = np.asarray(im)
    x = np.ascontiguousarray((rgb.astype(np.float32) * np.float32(manifest['input']['scale'])).transpose(2, 0, 1)[None])
    logits = session.run(None, {name: x})[0]
    assert logits.shape == (1, 6, 240, 320) and np.isfinite(logits).all()
    labels = logits[0].argmax(axis=0).astype(np.uint8)
    Image.fromarray(labels, 'L').save(out / filename.replace('.png', '.mask.png'))
    arr = rgb.astype(np.float32).copy()
    colors = {1:(0,220,255), 2:(0,220,255), 3:(255,210,0), 4:(255,110,0), 5:(0,235,75)}
    for idx, color in colors.items():
        m = labels == idx
        arr[m] = arr[m] * .45 + np.array(color, dtype=np.float32) * .55
    canvas = Image.new('RGB', (640, 270), 'white')
    canvas.paste(im, (0, 30))
    canvas.paste(Image.fromarray(arr.astype(np.uint8)), (320, 30))
    draw = ImageDraw.Draw(canvas)
    draw.text((5, 7), filename + ' ORIGINAL', fill='black')
    draw.text((325, 7), 'CANDIDATE only | green=drivable', fill='black')
    canvas.save(out / filename.replace('.png', '.overlay.png'))
    near = labels[144:]
    xs = np.nonzero(near == 5)[1]
    rows.append({'frame': filename, 'source_sha256': sha256(path.read_bytes()).hexdigest(), 'class_fraction': {c['name']: float((labels == c['index']).mean()) for c in manifest['output']['classes']}, 'near_drivable_fraction': float((near == 5).mean()), 'near_drivable_center_x': float(xs.mean()) if len(xs) else None})
report = {'status': 'candidate_only_not_human_truth', 'model_revision': manifest['model_revision'], 'model_sha256': manifest['files'][0]['sha256'], 'dataset': manifest['dataset'], 'frames': rows}
(out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
