import argparse, hashlib, json, time
from pathlib import Path
import cv2
import numpy as np
import torch

p = argparse.ArgumentParser()
p.add_argument('--architecture', choices=('pidnet', 'unet'), required=True)
p.add_argument('--root', type=Path, required=True)
p.add_argument('--frames', type=Path, required=True)
p.add_argument('--out', type=Path, required=True)
a = p.parse_args()
a.out.mkdir(parents=True, exist_ok=False)
source = np.load(a.frames)
frames = source['frames']
assert frames.dtype == np.uint8 and frames.shape[1:] == (240, 320, 3)
assert np.isfinite(source['stamp']).all()
device = torch.device('cuda')
assert torch.cuda.is_available()
torch.set_num_threads(4)
result = {'source_sha256': hashlib.sha256(a.frames.read_bytes()).hexdigest(), 'frames': len(frames), 'models': {}}
for arch in (a.architecture,):
    ck = a.root / 'runs' / arch / 'best.pt'
    if arch == 'pidnet':
        from pinky_pidnet.model import load_checkpoint
        model, _ = load_checkpoint(ck, device)
    else:
        from pinky_lane.checkpoints import load_model
        model, _, _, _ = load_model(ck, 'cuda', ignore_top=0)
    masks = []
    start = time.time()
    with torch.inference_mode():
        for i in range(0, len(frames), 8):
            batch = [cv2.cvtColor(f, cv2.COLOR_BGR2RGB).astype(np.float32).transpose(2, 0, 1) / 255 for f in frames[i:i+8]]
            x = torch.from_numpy(np.ascontiguousarray(np.stack(batch))).to(device)
            pred = model(x).argmax(1).cpu().numpy().astype(np.uint8)
            pred[:, :110] = 255
            masks.extend(pred)
    masks = np.stack(masks)
    assert masks.shape == (len(frames), 240, 320)
    counts = np.stack([np.count_nonzero(masks == k, axis=(1, 2)) for k in (1, 2)], axis=1)
    visible = counts >= 30
    def max_run(values):
        current = longest = 0
        for value in values:
            current = current + 1 if value else 0
            longest = max(longest, current)
        return longest
    report = {'checkpoint_sha256': hashlib.sha256(ck.read_bytes()).hexdigest(), 'elapsed_seconds': round(time.time()-start, 3),
              'lane_pixel_median': np.median(counts, axis=0).tolist(),
              'frames_both_visible': int(np.count_nonzero(visible.all(axis=1))),
              'frames_one_sided': int(np.count_nonzero(visible.sum(axis=1) == 1)),
              'frames_both_missing': int(np.count_nonzero(~visible.any(axis=1))),
              'longest_both_missing': max_run(~visible.any(axis=1)),
              'both_visibility_transitions': int(np.count_nonzero(np.diff(visible.all(axis=1).astype(int)))),
              'threshold_pixels': 30, 'roi': 'rows 110:240; raw argmax'}
    np.savez_compressed(a.out / (arch + '-masks.npz'), masks=masks, stamp=source['stamp'])
    result['models'][arch] = report
(a.out / 'report.json').write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps(result, indent=2), flush=True)

