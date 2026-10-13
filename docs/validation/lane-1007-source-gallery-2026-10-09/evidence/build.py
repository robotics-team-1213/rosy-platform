"""Present the proven 10/7 MCAP frames for candidate review, without labels."""

import argparse
import csv
import hashlib
import html
import json
import shutil
from pathlib import Path


INPUT_SHA256 = "036c620b8379a9945216b552f2915774941ae7f5377052388489009a126ed5a0"
SESSIONS = {"20261007T143038Z_rosy_60": 124, "20261007T143211Z_rosy_60": 83}
FIELDS = ("source_session", "frame_index", "header_stamp_ns", "log_ns", "topic",
          "bag_sha256", "image", "image_sha256", "same_lane_pair", "boundary_id_left",
          "boundary_id_right", "loss_cause", "reappearance_frame", "visible_drivable",
          "reviewer", "reviewed_at", "notes")
REVIEW_FIELDS = FIELDS[8:]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build(source: Path, out: Path):
    index = source / "verified-inputs.jsonl"
    if digest(index) != INPUT_SHA256:
        raise ValueError("proven input index changed")
    entries = [json.loads(line) for line in index.read_text(encoding="utf-8").splitlines()]
    if len(entries) != sum(SESSIONS.values()):
        raise ValueError("proven frame count changed")
    rows = []
    for session, count in SESSIONS.items():
        current = [entry for entry in entries if entry["source_session"] == session]
        if len(current) != count:
            raise ValueError(f"{session}: frame count changed")
        for frame_index, entry in enumerate(current):
            frame = entry["mcap"]["frame"]
            image = Path(entry["image"])
            if (entry["source_kind"] != "mcap" or entry["fixed_eval_overlap"] is not True
                    or image != source / session / f"{frame_index:06}.jpg"
                    or digest(image) != entry["image_sha256"]
                    or frame["image_sha256"] != entry["image_sha256"]):
                raise ValueError(f"{session} frame {frame_index}: source mismatch")
            rows.append({"source_session": session, "frame_index": frame_index,
                         "header_stamp_ns": frame["header_stamp_ns"], "log_ns": frame["log_ns"],
                         "topic": frame["topic"], "bag_sha256": entry["mcap"]["bags"][0]["sha256"],
                         "image": f"frames/{session}_{frame_index:06}.jpg",
                         "image_sha256": entry["image_sha256"],
                         **{field: "" for field in REVIEW_FIELDS}})
    if {entry["source_session"] for entry in entries} != set(SESSIONS):
        raise ValueError("unexpected source session")

    out.mkdir(parents=True, exist_ok=False)
    frames_dir = out / "frames"
    frames_dir.mkdir()
    for row in rows:
        shutil.copyfile(source / row["source_session"] / f'{row["frame_index"]:06}.jpg',
                        out / row["image"])
    queue = out / "candidate-review-queue.csv"
    with queue.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    page = ['<!doctype html><meta charset="utf-8"><title>10/7 MCAP 원본 후보</title>',
            '<style>body{font:16px system-ui;max-width:1000px;margin:2rem auto}'
            'section{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:1rem}'
            'figure{margin:0}img{width:320px;height:240px}figcaption{font-size:13px}</style>',
            '<h1>10/7 MCAP 원본 검수 후보</h1><p>사람 정답 아님. 모델 출력 없음. 0부터 시작하는 연속 프레임.</p>']
    for session in SESSIONS:
        page.append(f'<h2>{html.escape(session)}</h2><section>')
        for row in rows:
            if row["source_session"] == session:
                page.append(f'<figure><img src="{row["image"]}" loading="lazy">'
                            f'<figcaption>{row["frame_index"]} · {row["header_stamp_ns"]}</figcaption></figure>')
        page.append('</section>')
    gallery = out / "candidate-gallery.html"
    gallery.write_text("\n".join(page) + "\n", encoding="utf-8")
    receipt = {"schema": "rosy.lane-candidate-review-queue/1", "status": "candidate_only_not_human_truth",
               "source_kind": "mcap_proven_original", "source_index_sha256": INPUT_SHA256,
               "sessions": SESSIONS, "rows": len(rows), "human_approved_events": 0,
               "training_admission": False, "lane_follow_acceptance": False,
               "queue_sha256": digest(queue), "gallery_sha256": digest(gallery)}
    (out / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.out), ensure_ascii=False, indent=2))
