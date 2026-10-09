"""Lane-failure analysis loop: facts, rule fusion, canaries and the CLI steps after collect.

Synthetic frames only; no MCAP, model, VLM or network. The 9dfk 2026-10-09 case
(20261009T130633Z_rosy_41: nose to the arena wall, one transverse line, model right) is the
fixture for pose_off_lane: it must never become a label candidate.
"""
import argparse
import json
import math

import cv2
import numpy as np
import pytest

import lane_failure as lf
import lane_failure_loop as loop

CLASSES = [(0, "floor", "background"), (1, "lane_line", "lane_marking"), (2, "wall", "wall"),
           (3, "drivable", "drivable")]


def _scan(front_m, rear_m=0.1, forward_deg=180.0):
    n = 720
    inc = 2 * math.pi / n
    ranges = [2.0] * n
    for i in range(n):
        a = math.degrees(-math.pi + i * inc)
        if abs((a - forward_deg + 180) % 360 - 180) < 5:
            ranges[i] = front_m
        if abs(a) < 5:
            ranges[i] = rear_m
    return {"angle_min": -math.pi, "angle_increment": inc, "range_min": 0.05, "range_max": 12.0, "ranges": ranges}


def _across_map():
    cmap = np.zeros((240, 320), np.uint8)
    cmap[:120] = 2
    cmap[170:180, 0:320] = 1          # one tape line left to right: across the view
    return cmap


def _along_map():
    cmap = np.zeros((240, 320), np.uint8)
    for row in range(120, 240):       # two lines converging towards the horizon
        x = int(60 - (row - 120) * 0.4)
        cmap[row, max(0, x):max(0, x) + 8] = 1
        cmap[row, 250 + (row - 120) // 3:258 + (row - 120) // 3] = 1
    return cmap


def _summary(cmap, front, keep):
    img = np.full((240, 320, 3), 110, np.uint8)
    frame = {"lidar_front_m": front, "calibration_active": False, "keep": keep,
             "image": lf.image_facts(img), "model": lf.model_facts(cmap, CLASSES)}
    return lf.summarize([frame, frame, frame])


KEEP_9DFK = {"strategy": "none", "reason": "no_boundary", "paint_source_used": "learned",
             "paint_model_revision": "lane-seg-20261006-28e8454d", "boundaries": 0, "transverse": 1,
             "rejected": ["transverse"], "ground": "NOMINAL"}
VLM_9DFK = {"lines_direction": "across", "lane_line_count": 1, "wall_close": "yes", "on_road": "no"}


def test_runs_join_close_gaps_and_drop_short():
    flags = [0, 1, 1, 0, 1, 1, 0, 0, 0, 0, 1]
    times = [i * 0.25 for i in range(len(flags))]
    assert lf.runs(flags, times, merge_gap_s=0.5, min_frames=3) == [(1, 5)]
    assert lf.sample(1, 5, 3) == [1, 3, 5] and lf.sample(2, 3, 3) == [2, 3]


def test_lidar_front_uses_the_mount_forward_axis():
    assert lf.lidar_front_m(_scan(0.21), 180.0) == 0.21          # URDF: forward is 180 deg in the scan
    assert lf.lidar_front_m(_scan(0.21), 0.0) == 0.1             # the rear return is not the front
    assert lf.lidar_front_m(None, 180.0) is None


def test_model_facts_direction():
    across, along = lf.model_facts(_across_map(), CLASSES), lf.model_facts(_along_map(), CLASSES)
    assert across["lane_direction"] == "across" and across["fractions"]["wall"] == 0.5
    assert along["lane_direction"] == "along" and along["lane_near"] > lf.LANE_SEEN_FRACTION
    assert lf.model_facts(np.zeros((240, 320), np.uint8), CLASSES)["lane_direction"] == "none"


def test_parse_vlm_keeps_facts_and_rejects_the_rest():
    assert lf.parse_vlm('ok {"lines_direction": "Across", "lane_line_count": 1, "wall_close": "yes", '
                        '"on_road": "no"} done') == VLM_9DFK
    odd = lf.parse_vlm('{"lines_direction": "diagonal", "lane_line_count": 9, "wall_close": true}')
    assert odd == {"lines_direction": "unsure", "lane_line_count": None, "wall_close": "unsure", "on_road": "unsure"}
    assert lf.parse_vlm("BACK_AND_RETRY")["error"].startswith("unparsable")


def test_vlm_vote_majority_and_tie():
    vote = lf.vlm_vote([VLM_9DFK, VLM_9DFK, dict(VLM_9DFK, lines_direction="along", lane_line_count=2)])
    assert vote["lines_direction"] == "across" and vote["lane_line_count"] == 1 and vote["frames"] == 3
    tie = lf.vlm_vote([VLM_9DFK, dict(VLM_9DFK, lines_direction="along")])
    assert tie["lines_direction"] == "unsure"
    assert lf.vlm_vote([])["wall_close"] == "unsure"


def test_9dfk_wall_case_is_pose_never_a_label():
    summary = _summary(_across_map(), 0.21, KEEP_9DFK)
    ev = lf.evidence(summary, VLM_9DFK)
    assert ev["wall_close_lidar"] and ev["across_view"] and not ev["model_lane_along"]
    pose = lf.fuse(summary, VLM_9DFK, {"cause": "pose_off_lane", "confidence": 0.9, "reason": "wall"})
    assert pose["final"] == "pose_off_lane" and pose["route"] == "stuck_handoff"
    miss = lf.fuse(summary, VLM_9DFK, {"cause": "model_miss", "confidence": 0.9, "reason": "?"})
    assert miss["final"] is None and miss["route"] == "human_queue"
    assert "model_miss" not in pose["supported"]


def test_model_miss_needs_visible_paint_and_no_wall():
    summary = _summary(np.zeros((240, 320), np.uint8), 1.2, dict(KEEP_9DFK, transverse=0, rejected=[]))
    along = {"lines_direction": "along", "lane_line_count": 2, "wall_close": "no", "on_road": "yes"}
    got = lf.fuse(summary, along, {"cause": "model_miss", "confidence": 0.8, "reason": "tape visible"})
    assert got["final"] == "model_miss" and got["route"] == "label_candidate"
    none = {"lines_direction": "none", "lane_line_count": 0, "wall_close": "no", "on_road": "unsure"}
    assert lf.fuse(summary, none, {"cause": "model_miss", "confidence": 0.8, "reason": ""})["route"] == "human_queue"
    weak = lf.fuse(summary, along, {"cause": "model_miss", "confidence": 0.3, "reason": ""})
    assert weak["route"] == "human_queue" and "confidence" in weak["why"]
    assert lf.fuse(summary, along, None)["route"] == "human_queue"
    # Lines the model marks across the view are never a model miss, even with no wall close by.
    across = _summary(_across_map(), 1.2, dict(KEEP_9DFK, transverse=0))
    assert "model_miss" not in lf.fuse(across, along, None)["supported"]


def test_keeper_logic_needs_the_model_to_see_lines_along():
    summary = _summary(_along_map(), 1.0, dict(KEEP_9DFK, transverse=0))
    got = lf.fuse(summary, None, {"cause": "keeper_logic", "confidence": 0.7, "reason": "lines marked"})
    assert got["final"] == "keeper_logic" and got["route"] == "perception_issue"


def test_parse_verdicts_validation():
    tiles = {"T001": "s", "T002": "s"}
    rows = ['{"tile": "T001", "cause": "ok", "confidence": 0.9, "reason": "held"}',
            '{"tile": "T002", "cause": "pose_off_lane", "confidence": 1, "reason": "wall"}']
    got = lf.parse_verdicts(rows, tiles)
    assert got["T002"]["confidence"] == 1.0
    for bad in (rows[:1], rows + rows[:1], [rows[0], rows[1].replace("pose_off_lane", "turn_left")],
                [rows[0], rows[1].replace('"confidence": 1', '"confidence": 2')],
                [rows[0], rows[1].replace('"confidence": 1, ', '')],          # confidence is required
                [rows[0], '["T002", "ok"]']):                                  # not an object

        with pytest.raises(ValueError):
            lf.parse_verdicts(bad, tiles)


def test_canary_scoring_refuses_a_careless_reviewer():
    hidden = {f"C{i}": {"cause": c} for i, c in enumerate(("model_miss", "pose_off_lane", "camera_exposure", "ok"))}
    right = {t: {"cause": h["cause"]} for t, h in hidden.items()}
    assert lf.score_canaries(hidden, right, 12) == ({"count": 4, "caught": 4, "rate": 1.0}, {})
    with pytest.raises(ValueError, match="canaries for"):
        lf.score_canaries(hidden, right, 20)                     # 20 real tiles need 5
    wrong = dict(right, C0={"cause": "pose_off_lane"})
    with pytest.raises(lf.CanaryRefused, match="canary accuracy") as refused:
        lf.score_canaries(hidden, wrong, 12)
    assert "C0" not in str(refused.value) and "model_miss" not in str(refused.value)   # counts only
    assert refused.value.misses == {"C0": {"expected": "model_miss", "said": "pose_off_lane"}}


def test_canary_transforms():
    img = np.full((240, 320, 3), 120, np.uint8)
    assert lf.exposure_bad(lf.image_facts(lf.canary_image(img, "dark")))
    assert lf.exposure_bad(lf.image_facts(lf.canary_image(img, "bright")))
    assert not lf.exposure_bad(lf.image_facts(lf.canary_image(img, "ok_run")))
    erased = lf.canary_class_map(_along_map(), CLASSES, "erased_mask")
    assert not (erased == 1).any() and (lf.canary_class_map(_along_map(), CLASSES, "ok_run") == 1).any()
    for kind in ("keeper_drop", "erased_mask", "dark", "bright"):
        assert lf.canary_keep({"strategy": "both", "reason": None}, kind)["strategy"] == "none"
    assert lf.canary_keep({"strategy": "both", "reason": None}, "ok_run")["strategy"] == "both"


# --- CLI steps after collect (collect itself needs MCAP + ONNX; it ran on the model PC) ----------

def _tile(run, tid, cmap, front, keep, image_value=110):
    folder = run / "tiles" / tid
    folder.mkdir(parents=True)
    img = np.full((240, 320, 3), image_value, np.uint8)
    raw = cv2.imencode(".jpg", img)[1].tobytes()
    frames = []
    for k in range(3):
        (folder / f"f{k}.jpg").write_bytes(raw)
        cv2.imwrite(str(folder / f"f{k}-class.png"), cmap)
        frames.append({"ordinal": 10 + k, "t": 100.0 + k, "t_rel": 1.0 + k, "log_ns": 1, "lidar_front_m": front,
                       "calibration_active": False, "keep": keep, "image": lf.image_facts(img),
                       "model": lf.model_facts(cmap, CLASSES), "file": f"tiles/{tid}/f{k}.jpg",
                       "class_png": f"tiles/{tid}/f{k}-class.png", "image_sha256": loop._sha(raw),
                       "width": 320, "height": 240})
    return {"tile": tid, "session": {"session": "20261009T130633Z_rosy_41", "device": "rosy_41",
                                     "source_video": "20261009T130633Z_rosy_41/bag/bag_0.mcap",
                                     "source_video_sha256": "a" * 64},
            "t0": 0.0, "t1": 2.0, "n_frames": 30, "model": {"revision": "lane-seg-x", "source": "test",
                                                               "classes": CLASSES},
            "motion": {"moved_m": 0.0, "turned_deg": 0.0}, "keep_reason": keep["reason"], "paint_source": "learned",
            "frames": frames, "summary": lf.summarize(frames)}


@pytest.fixture
def run(tmp_path):
    run = tmp_path / "run1"
    run.mkdir()
    blank = np.zeros((240, 320), np.uint8)
    tiles = [_tile(run, "T001", _across_map(), 0.21, KEEP_9DFK),                       # 9dfk wall case
             _tile(run, "T002", blank, 1.2, dict(KEEP_9DFK, transverse=0, rejected=[])),  # a model miss
             *[_tile(run, f"T00{i}", blank, 1.0, dict(KEEP_9DFK, transverse=0)) for i in range(3, 7)]]
    loop._jsonl(run / "tiles.jsonl", tiles)
    (run / "key.json").write_text(json.dumps({f"T00{i}": {"cause": c, "kind": "test"} for i, c in
                                              zip(range(3, 7), ("model_miss", "camera_exposure", "ok", "ok"))}))
    (run / "run.json").write_text(json.dumps({"run": "run1", "tool_commit": "0" * 40}))
    return run


class _Vlm:
    model, digest, url = "stub-vlm", "sha256:stub", "stub"
    answers = {"T001": VLM_9DFK}

    def __init__(self):
        self.calls = 0

    def ask(self, bgr):
        self.calls += 1
        return json.dumps(VLM_9DFK if self.calls <= 3 else
                          {"lines_direction": "along", "lane_line_count": 2, "wall_close": "no", "on_road": "yes"})

    def unload(self):
        raise AssertionError("unload is opt-in")


def _verdicts(path, canary_t3="model_miss"):
    rows = [{"tile": "T001", "cause": "pose_off_lane", "confidence": 0.9, "reason": "nose to wall"},
            {"tile": "T002", "cause": "model_miss", "confidence": 0.8, "reason": "tape visible, no mask"},
            {"tile": "T003", "cause": canary_t3, "confidence": 0.8, "reason": "c"},
            {"tile": "T004", "cause": "camera_exposure", "confidence": 0.8, "reason": "c"},
            {"tile": "T005", "cause": "ok", "confidence": 0.8, "reason": "c"},
            {"tile": "T006", "cause": "ok", "confidence": 0.8, "reason": "c"}]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


def test_cli_vlm_sheets_import_fuse(run, tmp_path):
    assert loop.vlm(argparse.Namespace(run=run), backend=_Vlm())["asked"] == 18
    assert loop.vlm(argparse.Namespace(run=run), backend=_Vlm())["asked"] == 0     # resumable
    assert loop.sheets(argparse.Namespace(run=run, per_sheet=3)) == {"sheets": 2, "tiles": 6}
    assert "key" not in " ".join(p.name for p in (run / "sheets").iterdir())
    block = loop.import_verdicts(argparse.Namespace(run=run, verdicts=_verdicts(tmp_path / "v.jsonl"),
                                                    reviewer="claude-subagent"))
    assert block["rate"] == 1.0 and block["count"] == 4
    summary = loop.fuse_run(argparse.Namespace(run=run))
    assert summary["episodes"] == 2 and summary["final"]["pose_off_lane"] == 1
    assert summary["final"]["model_miss"] == 1 and summary["label_candidate_frames"] == 3
    stuck = loop._read_jsonl(run / "stuck-handoff.jsonl")
    assert [r["episode"] for r in stuck] == ["T001"]
    candidates = loop._read_jsonl(run / "label-candidates" / "verified-inputs.jsonl")
    assert {c["annotation_note"].split()[1] for c in candidates} == {"T002"}
    assert all(c["capture_group"] == "20261009T130633Z_rosy_41" and "mask" not in c for c in candidates)
    assert "| T001 |" in (run / "report.md").read_text(encoding="utf-8")
    # A second fuse rewrites label-candidates/: nothing stale survives, the file exists even when empty.
    (run / "label-candidates" / "images" / "stale.jpg").write_bytes(b"old")
    loop.fuse_run(argparse.Namespace(run=run))
    assert not (run / "label-candidates" / "images" / "stale.jpg").exists()
    (run / "verdicts.jsonl").write_text("")
    with pytest.raises(ValueError, match="differ from what import-verdicts recorded"):
        loop.fuse_run(argparse.Namespace(run=run))


def test_cli_fuse_writes_empty_candidates(run, tmp_path):
    loop.sheets(argparse.Namespace(run=run, per_sheet=3))
    rows = _verdicts(tmp_path / "v.jsonl").read_text().replace('"cause": "model_miss", "confidence": 0.8, "reason": "tape',
                                                              '"cause": "model_miss", "confidence": 0.3, "reason": "tape')
    (tmp_path / "v2.jsonl").write_text(rows)
    loop.import_verdicts(argparse.Namespace(run=run, verdicts=tmp_path / "v2.jsonl", reviewer="r"))
    assert loop.fuse_run(argparse.Namespace(run=run))["label_candidate_frames"] == 0
    assert (run / "label-candidates" / "verified-inputs.jsonl").read_text() == ""


def test_cli_import_refuses_facts_changed_after_sheets(run, tmp_path):
    loop.vlm(argparse.Namespace(run=run), backend=_Vlm())
    loop.sheets(argparse.Namespace(run=run, per_sheet=3))
    with (run / "vlm.jsonl").open("a") as fh:
        fh.write("\n")
    with pytest.raises(ValueError, match="vlm.jsonl changed"):
        loop.import_verdicts(argparse.Namespace(run=run, verdicts=_verdicts(tmp_path / "v.jsonl"), reviewer="r"))


def test_cli_import_refuses_missed_canaries(run, tmp_path):
    loop.sheets(argparse.Namespace(run=run, per_sheet=3))
    with pytest.raises(ValueError, match="canary accuracy"):
        loop.import_verdicts(argparse.Namespace(run=run, verdicts=_verdicts(tmp_path / "v.jsonl", "ok"),
                                                reviewer="careless"))
    assert (run / "review-refused.json").exists() and not (run / "review.json").exists()
    refused = (run / "review-refused.json").read_text(encoding="utf-8")
    assert "T003" not in refused and "expected" not in refused and '"caught": 3' in refused
    misses = json.loads((run / "canary-misses.json").read_text(encoding="utf-8"))
    assert misses == {"T003": {"expected": "model_miss", "said": "ok"}}
    assert not any("miss" in p.name for p in (run / "sheets").iterdir())
    # One try per run, even with correct answers now: the reviewer has seen these canaries.
    with pytest.raises(ValueError, match="collect a new run"):
        loop.import_verdicts(argparse.Namespace(run=run, verdicts=_verdicts(tmp_path / "v2.jsonl"),
                                                reviewer="second try"))
