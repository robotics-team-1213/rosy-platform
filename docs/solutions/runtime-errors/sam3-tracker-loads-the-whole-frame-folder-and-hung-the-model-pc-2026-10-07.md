---
title: The SAM 3 tracker loads its whole frame folder at 1008 px float and a full session hung the 15 GB model PC
date: 2026-10-07
category: runtime-errors
module: learning/training/perception/dataset (sam3_road_draft.py, D-465 addendum 2026-10-07)
problem_type: runtime_error
component: tooling
symptoms:
  - "model PC answered ping but SSH timed out during banner exchange on both LAN addresses"
  - "first run of sam3_road_draft on a 642-frame session took 442 s instead of the pilot's ~4.5 min"
  - "second run never returned; the machine needed a power cycle"
root_cause: wrong_api
resolution_type: code_fix
severity: high
tags: [sam3, tracker, memory, model-pc, video, ram]
---

# The SAM 3 tracker loads its whole frame folder at 1008 px float and a full session hung the 15 GB model PC

## Problem

`sam3_road_draft.py` gave the SAM 3.0 tracker (`build_sam3_video_model().tracker`) the folder holding every frame of a session and then tracked one 15-frame keyframe segment at a time. The model PC (15 GB RAM, ZFS zvol swap) went into swap on the first run and hung on the second.

## Symptoms

- Ping worked, but `ssh` timed out at the banner exchange on the Wi-Fi address and could not connect at all on the Ethernet one.
- The first full run took 442 s; the 20-frame pilot on the same hardware had been fast.
- Nothing returned an error. The OOM killer did not step in before the box stopped responding.

## What Didn't Work

- Setting `offload_video_to_cpu=True` only moves the frame tensor from GPU memory to host RAM. That relieves VRAM (peak 7.3 GB) and loads the RAM instead.
- `clear_all_points_in_video` between segments resets points and per-object outputs, but leaves the loaded frames in place.

## Solution

Give the tracker a folder that holds only the current segment, start a fresh state for each segment, and map indices back:

```python
def segment_dir(frames, k, every, n):
    seg = Path(frames).parent / "segment"
    shutil.rmtree(seg, ignore_errors=True)
    seg.mkdir()
    for j, fi in enumerate(range(k, min(n, k + every))):
        shutil.copy(Path(frames) / f"{fi:05d}.jpg", seg / f"{j:05d}.jpg")
    return seg

# per keyframe k:
state = tracker.init_state(video_path=str(seg), offload_video_to_cpu=True, async_loading_frames=False)
tracker.add_new_points_or_box(inference_state=state, frame_idx=0, ...)
for j, _, _, masks, _ in tracker.propagate_in_video(state, start_frame_idx=0, max_frame_num_to_track=every - 1, ...):
    carpet[k + j] = ...
```

A test in `test_sam3_road_draft.py` uses a fake tracker to check that no segment exceeds `every` frames, that each segment is seeded at its frame 0, and that every video frame gets a mask exactly once.

The fix has not yet been re-run on the model PC, because the PC was still down when this was written.

## Why This Works

`load_video_frames_from_jpg_images` in the external [facebookresearch/sam3](https://github.com/facebookresearch/sam3) package (file `sam3/model/utils/sam2_utils.py` at upstream commit `2345a4ad`, the copy installed on the model PC; not a path or commit in this repository) reads every JPEG in the folder into one tensor up front, unless async loading is on. The tensor is `torch.zeros(num_frames, 3, image_size, image_size, dtype=torch.float32)`, and the builder sets `image_size=1008`. That is about 12 MB per frame no matter how small the source is (320×240 here). 642 frames come to about 7.8 GB before the image and video models are counted. A 15-frame segment is about 180 MB.

## Prevention

- Treat SAM 3 / SAM 2 `init_state(video_path=...)` as "load the whole folder into RAM". Size it as `frames × 12 MB` against the host's free RAM before pointing it at a session.
- Keep `async_loading_frames=False` when the folder is deleted right after use. The async loader reads in a background thread.
- The model PC has 15 GB of RAM and a zvol swap that can hang under pressure (auto memory [claude]). Any job that grows with session length needs a bound, not a bigger machine.

## Related Issues

- Design and pilot numbers: `docs/plans/2026-10-06-qwen-point-sam3-lane-drafts-design.md`
- D-465 addendum 2026-10-07 (SAM 3 + VLM point drivable drafts)
