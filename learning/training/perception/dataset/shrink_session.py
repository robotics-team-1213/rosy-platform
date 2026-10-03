"""Shrink a D-356 recording session whose size is dominated by raw camera images.

Usage: shrink_session.py <session> [--quality 90] [--no-verify]
Writes <session>.compact/ next to the source (never modifies it): every bag/*.mcap is
rewritten with sensor_msgs/msg/Image (bgr8/rgb8/mono8) turned into
sensor_msgs/msg/CompressedImage JPEG on <topic>/compressed (same header, same log/publish
time, same sequence); every other message is copied byte for byte with its schema and
channel. Chunks are zstd. session.json is copied plus "source_fingerprint" (path+size
sha256, not a content hash) and "jpeg_quality"; bag/metadata.yaml is regenerated with the
camera topic renamed. Not copied: record.log and any other file outside session.json and
bag/*.mcap. Refuses a session whose ended_at is null unless --force.
"""
import argparse
import copy
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from extract import _mcap_files  # noqa: E402

IMAGE = "sensor_msgs/msg/Image"
COMPRESSED = "sensor_msgs/msg/CompressedImage"
COMPRESSED_DEF = """std_msgs/Header header
string format
uint8[] data
================================================================================
MSG: std_msgs/Header
builtin_interfaces/Time stamp
string frame_id
================================================================================
MSG: builtin_interfaces/Time
int32 sec
uint32 nanosec
"""
# Jazzy sensor_msgs/msg/CompressedImage, from
# /opt/ros/jazzy/share/sensor_msgs/msg/CompressedImage.json type_hashes.
COMPRESSED_IMAGE_HASH = "RIHS01_15640771531571185e2efc8a100baf923961a4d15d5569652e6cb6691e8e371a"
CHANNELS = {"bgr8": 3, "rgb8": 3, "mono8": 1}


def _need_mcap():
    try:
        from mcap.reader import make_reader
        from mcap.writer import CompressionType, Writer
        from mcap_ros2._dynamic import serialize_dynamic
        from mcap_ros2.decoder import DecoderFactory
    except ImportError:
        raise SystemExit("needs: pip install mcap mcap-ros2-support")
    return make_reader, Writer, CompressionType, serialize_dynamic, DecoderFactory


def source_fingerprint(session: Path) -> str:
    """sha256 over sorted 'relative path<TAB>size' lines of every file in the session.

    A path+size fingerprint, not a content hash: it identifies the source file list cheaply."""
    lines = sorted(f"{p.relative_to(session).as_posix()}\t{p.stat().st_size}"
                   for p in Path(session).rglob("*") if p.is_file())
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def _to_array(img):
    """Decoded Image message -> BGR (or gray) array for cv2, or None if unsupported."""
    ch = CHANNELS.get(img.encoding)
    if ch is None or img.width == 0 or img.height == 0:
        return None
    row = img.width * ch
    if img.step < row or len(img.data) < img.step * img.height:
        return None
    buf = np.frombuffer(bytes(img.data), np.uint8)[: img.step * img.height]
    arr = buf.reshape(img.height, img.step)[:, :row]
    if ch == 3:
        arr = arr.reshape(img.height, img.width, 3)
        if img.encoding == "rgb8":
            arr = arr[..., ::-1]
    return np.ascontiguousarray(arr)


def compact_mcap(src: Path, dst: Path, quality: int = 90) -> dict:
    make_reader, Writer, CompressionType, serialize_dynamic, DecoderFactory = _need_mcap()
    encode = serialize_dynamic(COMPRESSED, COMPRESSED_DEF)[COMPRESSED]
    decoders = {}
    stats = {"messages": 0, "converted": 0, "passthrough_images": 0, "topics": {}}
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        reader = make_reader(fin)
        writer = Writer(fout, compression=CompressionType.ZSTD)
        writer.start(profile=reader.get_header().profile, library="shrink_session.py")
        schema_ids, chan_ids = {}, {}
        comp_schema = None

        for schema, ch, m in reader.iter_messages():
            stats["messages"] += 1
            out = None
            if schema is not None and schema.name == IMAGE and ch.message_encoding == "cdr":
                dec = decoders.get(schema.id)
                if dec is None:
                    dec = decoders[schema.id] = DecoderFactory().decoder_for(
                        ch.message_encoding, schema)
                ok = False
                try:
                    img = dec(m.data)
                    arr = _to_array(img)
                    if arr is not None:
                        ok, jpg = cv2.imencode(".jpg", arr, [cv2.IMWRITE_JPEG_QUALITY, quality])
                except Exception:  # noqa: BLE001 - undecodable frame: keep it as recorded
                    ok = False
                if ok:
                    if comp_schema is None:
                        comp_schema = writer.register_schema(
                            COMPRESSED, "ros2msg", COMPRESSED_DEF.encode())
                    key = ("c", ch.id)
                    if key not in chan_ids:
                        meta = {k: v for k, v in ch.metadata.items() if k != "topic_type_hash"}
                        chan_ids[key] = writer.register_channel(
                            ch.topic + "/compressed", "cdr", comp_schema, meta)
                    data = encode({"header": {"stamp": {"sec": img.header.stamp.sec,
                                                        "nanosec": img.header.stamp.nanosec},
                                              "frame_id": img.header.frame_id},
                                   "format": "jpeg", "data": jpg.tobytes()})
                    out = (chan_ids[key], data, ch.topic + "/compressed", ch.topic)
                    stats["converted"] += 1
                else:
                    stats["passthrough_images"] += 1
            if out is None:
                sid = 0
                if schema is not None:
                    if schema.id not in schema_ids:
                        schema_ids[schema.id] = writer.register_schema(
                            schema.name, schema.encoding, schema.data)
                    sid = schema_ids[schema.id]
                key = ("r", ch.id)
                if key not in chan_ids:
                    chan_ids[key] = writer.register_channel(
                        ch.topic, ch.message_encoding, sid, ch.metadata)
                out = (chan_ids[key], m.data, ch.topic, ch.topic)
            t = stats["topics"].setdefault(out[2], [out[3], 0])
            t[1] += 1
            writer.add_message(out[0], m.log_time, out[1], m.publish_time, m.sequence)
        for att in reader.iter_attachments():
            writer.add_attachment(att.create_time, att.log_time, att.name, att.media_type,
                                  att.data)
        for md in reader.iter_metadata():
            writer.add_metadata(md.name, md.metadata)
        writer.finish()
    return stats


def shrink_session(src, quality: int = 90, force: bool = False) -> Path:
    src = Path(src)
    sj = src / "session.json"
    if not force and sj.is_file() and \
            json.loads(sj.read_text(encoding="utf-8")).get("ended_at", "") is None:
        raise SystemExit(f"{src.name} has ended_at null (still recording?); use --force")
    files = _mcap_files(src)
    if not files:
        raise SystemExit(f"no .mcap files under {src / 'bag'}")
    out = src.with_name(src.name + ".compact")
    if out.exists():
        raise SystemExit(f"{out} already exists; refusing to overwrite")
    tmp = src.with_name(src.name + ".compact.partial")
    if tmp.exists():
        shutil.rmtree(tmp)
    (tmp / "bag").mkdir(parents=True)
    totals = {}
    try:
        for f in files:
            t0 = time.time()
            st = compact_mcap(f, tmp / "bag" / f.name, quality)
            for k, (origin, n) in st["topics"].items():
                totals.setdefault(k, [origin, 0])[1] += n
            print(f"  {f.name}: {st['messages']} msgs, {st['converted']} frames -> JPEG "
                  f"({time.time() - t0:.1f}s)", flush=True)
        _write_bag_metadata(src, tmp, totals)
        meta = {}
        if (src / "session.json").is_file():
            meta = json.loads((src / "session.json").read_text(encoding="utf-8"))
        meta["source_fingerprint"] = source_fingerprint(src)
        meta["jpeg_quality"] = quality
        (tmp / "session.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        tmp.rename(out)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return out


def _write_bag_metadata(src: Path, tmp: Path, totals: dict) -> None:
    """bag/metadata.yaml for the new bag: the source's, with the camera topic renamed.

    Message counts, file list and times are unchanged (same messages, same log times).
    The compressed topic carries COMPRESSED_IMAGE_HASH (rosbag2 requires the key).
    """
    mp = src / "bag" / "metadata.yaml"
    if not mp.is_file():
        print("  warning: source has no bag/metadata.yaml; run `ros2 bag reindex` on the output",
              file=sys.stderr)
        return
    import yaml
    doc = yaml.safe_load(mp.read_text(encoding="utf-8"))
    info = doc["rosbag2_bagfile_information"]
    by_name = {t["topic_metadata"]["name"]: t for t in info["topics_with_message_count"]}
    topics = []
    for name, (origin, n) in totals.items():
        entry = copy.deepcopy(by_name[origin])
        if name != origin:
            entry["topic_metadata"]["name"] = name
            entry["topic_metadata"]["type"] = COMPRESSED
            entry["topic_metadata"]["type_description_hash"] = COMPRESSED_IMAGE_HASH
        entry["message_count"] = n
        topics.append(entry)
    info["topics_with_message_count"] = topics
    (tmp / "bag" / "metadata.yaml").write_text(yaml.safe_dump(doc, sort_keys=False),
                                               encoding="utf-8")


def _psnr(a, b) -> float:
    mse = float(np.mean((a.astype(np.float64) - b.astype(np.float64)) ** 2))
    return float("inf") if mse == 0 else float(10 * np.log10(255.0 ** 2 / mse))


def verify_session(src, dst, sample: int = 50) -> dict:
    """Per-topic counts (camera topic renamed), timestamps, and PSNR of sampled frames.

    Frames are matched by (stamp, log_time); only every Nth raw frame is kept in memory.
    """
    make_reader, _, _, _, DecoderFactory = _need_mcap()
    src, dst = Path(src), Path(dst)

    def scan(session, keep):
        times, frames = {}, {}
        n = 0
        for f in _mcap_files(session):
            with open(f, "rb") as fh:
                r = make_reader(fh, decoder_factories=[DecoderFactory()])
                for schema, ch, m, msg in r.iter_decoded_messages():
                    topic = ch.topic
                    is_cam = schema.name in (IMAGE, COMPRESSED)
                    if schema.name == COMPRESSED:
                        topic = topic[: -len("/compressed")]
                    times.setdefault(topic, []).append((m.log_time, m.publish_time, m.sequence))
                    if is_cam:
                        key = (msg.header.stamp.sec, msg.header.stamp.nanosec, m.log_time)
                        if keep(n, key):
                            frames[key] = (_to_array(msg) if schema.name == IMAGE
                                           else bytes(msg.data))
                        n += 1
        return times, frames, n

    tb, fb, nb = scan(dst, lambda n, k: True)  # JPEG bytes are small: keep all
    step = max(1, nb // max(sample, 1))
    ta, fa, _ = scan(src, lambda n, k: n % step == 0)
    counts = {t: (len(v), len(tb.get(t, []))) for t, v in ta.items()}
    vals = []
    for key, arr in fa.items():
        if arr is None or key not in fb:
            continue
        dec = cv2.imdecode(np.frombuffer(fb[key], np.uint8),
                           cv2.IMREAD_GRAYSCALE if arr.ndim == 2 else cv2.IMREAD_COLOR)
        vals.append(_psnr(arr, dec))
    return {"counts": counts,
            "counts_equal": set(ta) == set(tb) and all(a == b for a, b in counts.values()),
            "timestamps_equal": ta == tb,
            "psnr_n": len(vals),
            "psnr_min": min(vals) if vals else None,
            "psnr_mean": float(np.mean(vals)) if vals else None}


def _size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("session")
    ap.add_argument("--quality", type=int, default=90)
    ap.add_argument("--force", action="store_true",
                    help="convert even if session.json has ended_at null")
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--sample", type=int, default=50)
    args = ap.parse_args(argv)
    src = Path(args.session)
    t0 = time.time()
    out = shrink_session(src, args.quality, args.force)
    print(f"{src.name}: {_size(src) / 1e6:.1f} MB -> {_size(out) / 1e6:.1f} MB "
          f"in {time.time() - t0:.0f}s -> {out}", flush=True)
    if args.no_verify:
        return 0
    rep = verify_session(src, out, args.sample)
    print(json.dumps(rep, indent=2))
    return 0 if rep["counts_equal"] and rep["timestamps_equal"] else 1


if __name__ == "__main__":
    sys.exit(main())
