import json

import numpy as np
import pytest

pytest.importorskip("mcap_ros2")
import yaml
from mcap.reader import make_reader
from mcap_ros2.decoder import DecoderFactory
from mcap_ros2.writer import Writer

import extract
import shrink_session as ss

HEADER_DEF = """std_msgs/Header header
"""
TIME_DEPS = """================================================================================
MSG: std_msgs/Header
builtin_interfaces/Time stamp
string frame_id
================================================================================
MSG: builtin_interfaces/Time
int32 sec
uint32 nanosec
"""
IMAGE_DEF = ("std_msgs/Header header\nuint32 height\nuint32 width\nstring encoding\n"
             "uint8 is_bigendian\nuint32 step\nuint8[] data\n" + TIME_DEPS)
STRING_DEF = "string data\n"


def _frame(i, h=48, w=64):
    y, x = np.mgrid[0:h, 0:w]
    bgr = np.stack([(x * 3 + i * 5) % 256, (y * 4) % 256, (x + y + i) % 256], -1)
    return bgr.astype(np.uint8)


def _image(i, encoding, step_pad=0):
    bgr = _frame(i)
    arr = {"bgr8": bgr, "rgb8": bgr[..., ::-1], "mono8": bgr[..., 0]}[encoding]
    h, w = arr.shape[:2]
    rows = arr.reshape(h, -1)
    if step_pad:
        rows = np.hstack([rows, np.zeros((h, step_pad), np.uint8)])
    return {"header": {"stamp": {"sec": 100 + i, "nanosec": 7}, "frame_id": "cam"},
            "height": h, "width": w, "encoding": encoding, "is_bigendian": 0,
            "step": rows.shape[1], "data": rows.tobytes()}


def make_session(root, encoding="bgr8", n=6, step_pad=0, name="s1", files=2,
                 ended_at="2026-01-01T00:00:00+00:00"):
    sess = root / name
    (sess / "bag").mkdir(parents=True)
    (sess / "session.json").write_text(json.dumps({"device": "d", "topics": ["camera/front"], "ended_at": ended_at}))
    for f in range(files):
        with open(sess / "bag" / f"bag_{f}.mcap", "wb") as fh:
            w = Writer(fh)
            img = w.register_msgdef("sensor_msgs/msg/Image", IMAGE_DEF)
            st = w.register_msgdef("std_msgs/msg/String", STRING_DEF)
            for i in range(n):
                k = f * n + i
                w.write_message("/r/camera/front", img, _image(k, encoding, step_pad),
                                log_time=1000 + k * 10, publish_time=1000 + k * 10 - 1, sequence=k)
                w.write_message("/r/line/observation", st, {"data": json.dumps({"k": k})},
                                log_time=1005 + k * 10, publish_time=1005 + k * 10)
            w.finish()
    return sess


def read_all(path):
    with open(path, "rb") as fh:
        r = make_reader(fh, decoder_factories=[DecoderFactory()])
        return [(s.name, c.topic, m.log_time, m.publish_time, m.sequence, d)
                for s, c, m, d in r.iter_decoded_messages()]


def all_msgs(sess):
    out = []
    for f in extract._mcap_files(sess):
        out += read_all(f)
    return out


@pytest.mark.parametrize("enc,pad", [("bgr8", 0), ("rgb8", 0), ("mono8", 0), ("bgr8", 6)])
def test_shrink_renames_and_preserves(tmp_path, enc, pad):
    src = make_session(tmp_path, enc, step_pad=pad)
    out = ss.shrink_session(src, quality=90)
    assert out == tmp_path / "s1.compact"
    a, b = all_msgs(src), all_msgs(out)
    assert len(a) == len(b)
    for (sn, st, sl, sp, sq, sd), (dn, dt, dl, dp, dq, dd) in zip(a, b):
        assert (sl, sp, sq) == (dl, dp, dq)
        if st.endswith("/camera/front"):
            assert dn == "sensor_msgs/msg/CompressedImage" and dt == st + "/compressed"
            assert dd.header.stamp.sec == sd.header.stamp.sec
            assert dd.header.stamp.nanosec == sd.header.stamp.nanosec
            assert dd.header.frame_id == sd.header.frame_id
            assert dd.format == "jpeg" and bytes(dd.data)[:2] == b"\xff\xd8"
        else:
            assert (dn, dt) == (sn, st) and dd.data == sd.data


def test_session_json_and_source_untouched(tmp_path):
    src = make_session(tmp_path)
    before = {p.name: p.read_bytes() for p in src.rglob("*") if p.is_file()}
    out = ss.shrink_session(src, quality=75)
    assert {p.name: p.read_bytes() for p in src.rglob("*") if p.is_file()} == before
    meta = json.loads((out / "session.json").read_text())
    assert meta["jpeg_quality"] == 75 and meta["device"] == "d"
    assert meta["source_fingerprint"] == ss.source_fingerprint(src)
    assert len(meta["source_fingerprint"]) == 64


def test_refuses_existing_output(tmp_path):
    src = make_session(tmp_path)
    (tmp_path / "s1.compact").mkdir()
    with pytest.raises(SystemExit):
        ss.shrink_session(src)


def test_uses_zstd_chunks(tmp_path):
    out = ss.shrink_session(make_session(tmp_path))
    with open(out / "bag" / "bag_0.mcap", "rb") as fh:
        s = make_reader(fh).get_summary()
    assert s.chunk_indexes and all(c.compression == "zstd" for c in s.chunk_indexes)


def test_verify_reports_psnr_and_counts(tmp_path):
    src = make_session(tmp_path)
    out = ss.shrink_session(src, quality=90)
    rep = ss.verify_session(src, out, sample=5)
    assert rep["counts_equal"] and rep["timestamps_equal"]
    assert rep["psnr_min"] >= 38.0


def test_verify_detects_count_mismatch(tmp_path):
    src = make_session(tmp_path)
    out = ss.shrink_session(src)
    other = make_session(tmp_path, n=3, name="s2")
    rep = ss.verify_session(other, out)
    assert not rep["counts_equal"]


def test_extract_reads_compact(tmp_path):
    src = make_session(tmp_path)
    out = ss.shrink_session(src)
    dst = tmp_path / "frames"
    assert extract.main([str(out), "--out", str(dst), "--min-interval", "0"]) == 0
    rows = [json.loads(l) for l in (dst / "frames.jsonl").read_text().splitlines()]
    assert rows and all(r["stamp_ns"] // 10**9 >= 100 for r in rows)
    assert any((dst / "frames").glob("*.jpg"))


def _write_bag_metadata(sess, n=6, files=2):
    meta = {"rosbag2_bagfile_information": {
        "version": 9, "storage_identifier": "mcap", "message_count": 2 * n * files,
        "topics_with_message_count": [
            {"topic_metadata": {"name": "/r/camera/front", "type": IMAGE_T,
                                "serialization_format": "cdr", "offered_qos_profiles": [],
                                "type_description_hash": "RIHS01_x"},
             "message_count": n * files},
            {"topic_metadata": {"name": "/r/line/observation", "type": "std_msgs/msg/String",
                                "serialization_format": "cdr", "offered_qos_profiles": [],
                                "type_description_hash": "RIHS01_y"},
             "message_count": n * files}],
        "relative_file_paths": [f"bag_{f}.mcap" for f in range(files)],
        "files": [{"path": f"bag_{f}.mcap", "message_count": 2 * n} for f in range(files)]}}
    (sess / "bag" / "metadata.yaml").write_text(yaml.safe_dump(meta))


IMAGE_T = "sensor_msgs/msg/Image"


def test_refuses_unfinished_session_unless_forced(tmp_path):
    src = make_session(tmp_path, ended_at=None)
    with pytest.raises(SystemExit):
        ss.shrink_session(src)
    assert not (tmp_path / "s1.compact").exists()
    assert ss.shrink_session(src, force=True).is_dir()


def test_writes_rosbag2_metadata(tmp_path):
    src = make_session(tmp_path)
    _write_bag_metadata(src)
    out = ss.shrink_session(src)
    info = yaml.safe_load((out / "bag" / "metadata.yaml").read_text())["rosbag2_bagfile_information"]
    topics = {t["topic_metadata"]["name"]: t for t in info["topics_with_message_count"]}
    assert set(topics) == {"/r/camera/front/compressed", "/r/line/observation"}
    cam = topics["/r/camera/front/compressed"]
    assert cam["topic_metadata"]["type"] == "sensor_msgs/msg/CompressedImage"
    assert cam["topic_metadata"]["type_description_hash"] == ss.COMPRESSED_IMAGE_HASH
    assert ss.COMPRESSED_IMAGE_HASH.startswith("RIHS01_") and cam["message_count"] == 12
    assert topics["/r/line/observation"]["topic_metadata"]["type_description_hash"] == "RIHS01_y"
    assert info["message_count"] == 24 and info["storage_identifier"] == "mcap"
    assert info["relative_file_paths"] == ["bag_0.mcap", "bag_1.mcap"]
