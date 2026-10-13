"""Prove reviewed image pixels against captured rosbag2 MCAP bytes."""
import hashlib
import os
import tempfile
from importlib.metadata import version
from pathlib import Path

import cv2
import numpy as np
import yaml

from extract import (_header_stamp_ns, _mcap_files, _topic_is, image_to_bgr,
                     CAMERA_TOPIC, COMPRESSED_CAMERA_TOPIC)


def _capture(source: Path, target: Path) -> str:
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"MCAP source is missing or linked: {source}")
    digest = hashlib.sha256()
    with source.open("rb") as incoming, target.open("xb") as snapshot:
        for block in iter(lambda: incoming.read(1 << 20), b""):
            digest.update(block)
            snapshot.write(block)
    copied = hashlib.sha256()
    with target.open("rb") as snapshot:
        for block in iter(lambda: snapshot.read(1 << 20), b""):
            copied.update(block)
    if copied.digest() != digest.digest():
        raise ValueError("MCAP snapshot changed while capturing")
    return digest.hexdigest()


def prove_frames(session, rows, scratch_parent, *, expected=None) -> dict:
    """rows: exact topic/log_ns/image plus optional bag/channel_id/message_ordinal."""
    from mcap.reader import make_reader
    from mcap_ros2.decoder import DecoderFactory

    session = Path(session)
    scratch_parent = Path(scratch_parent).resolve()
    if os.name == "nt" and not scratch_parent.is_relative_to(Path("X:/DevTemp").resolve()):
        raise ValueError("MCAP proof scratch must be under X:/DevTemp")
    if session.name.endswith(".compact"):
        raise ValueError("compact MCAP needs original-to-compact equivalence proof")
    if not rows or not isinstance(rows, list):
        raise ValueError("nonempty MCAP frame selection required")
    if session.is_symlink() or (session / "bag").is_symlink():
        raise ValueError("linked MCAP source refused")
    metadata = session / "bag" / "metadata.yaml"
    if metadata.is_symlink() or not metadata.is_file():
        raise ValueError("rosbag2 metadata.yaml required")
    meta_bytes = metadata.read_bytes()
    metadata_hash = hashlib.sha256(meta_bytes).hexdigest()
    if expected is not None and (not isinstance(expected, dict)
                                 or expected.get("metadata_sha256") != metadata_hash
                                 or not isinstance(expected.get("bags"), list)):
        raise ValueError("frozen MCAP metadata hash differs")
    info = yaml.safe_load(meta_bytes).get("rosbag2_bagfile_information")
    files = _mcap_files(session)
    listed = info.get("relative_file_paths") if isinstance(info, dict) else None
    if not files or listed != [path.name for path in files]:
        raise ValueError("MCAP metadata order differs from numeric bag order")
    wanted = {}
    for row in rows:
        if (not isinstance(row, dict) or not {"topic", "log_ns", "image"} <= row.keys()
                or type(row["log_ns"]) is not int or row["log_ns"] < 0
                or not isinstance(row["topic"], str)
                or not any(_topic_is(row["topic"], name)
                           for name in (CAMERA_TOPIC, COMPRESSED_CAMERA_TOPIC))):
            raise ValueError("exact camera topic/log_ns/image selection required")
        image = Path(row["image"])
        if image.is_symlink():
            raise ValueError("linked review image refused")
        raw = image.read_bytes()
        pixels = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if pixels is None:
            raise ValueError("review image cannot be decoded")
        key = (row["topic"], row["log_ns"])
        wanted.setdefault(key, []).append((row, hashlib.sha256(raw).hexdigest(), pixels))
    matches = {key: [] for key in wanted}
    bag_hashes = []
    with tempfile.TemporaryDirectory(prefix="mcap-proof-", dir=scratch_parent) as temp:
        for path in files:
            snapshot = Path(temp) / path.name
            digest = _capture(path, snapshot)
            bag_hashes.append({"name": path.name, "sha256": digest})
            if expected is not None and expected["bags"][:len(bag_hashes)] != bag_hashes:
                raise ValueError("frozen MCAP bag hash differs")
            with snapshot.open("rb") as stream:
                reader = make_reader(stream, decoder_factories=[DecoderFactory()])
                for ordinal, (_, channel, message, decoded) in enumerate(reader.iter_decoded_messages()):
                    key = (channel.topic, message.log_time)
                    if key not in matches:
                        continue
                    if _topic_is(channel.topic, COMPRESSED_CAMERA_TOPIC):
                        pixels = cv2.imdecode(np.frombuffer(bytes(decoded.data), np.uint8), cv2.IMREAD_COLOR)
                    else:
                        pixels = image_to_bgr(decoded.encoding, decoded.width, decoded.height,
                                              decoded.step, bytes(decoded.data))
                    if pixels is None:
                        raise ValueError("MCAP image cannot be decoded")
                    matches[key].append((path.name, channel.id, ordinal, _header_stamp_ns(decoded), pixels))
    if expected is not None and expected.get("bags") != bag_hashes:
        raise ValueError("frozen MCAP bag inventory differs")
    proved = []
    for key, requests in wanted.items():
        candidates = matches[key]
        for row, image_hash, pixels in requests:
            chosen = [item for item in candidates
                      if (row.get("bag") is None or item[0] == row["bag"])
                      and (row.get("channel_id") is None or item[1] == row["channel_id"])
                      and (row.get("message_ordinal") is None or item[2] == row["message_ordinal"])]
            if len(chosen) != 1:
                raise ValueError("MCAP frame missing or ambiguous; bag/channel/ordinal required")
            bag, channel, ordinal, stamp, decoded = chosen[0]
            if stamp is None or decoded.shape != pixels.shape or not np.array_equal(decoded, pixels):
                raise ValueError("MCAP decoded pixels or camera header differ from reviewed image")
            if row.get("header_stamp_ns") is not None and row["header_stamp_ns"] != stamp:
                raise ValueError("MCAP camera header stamp differs")
            proved.append({"topic": key[0], "log_ns": key[1], "bag": bag,
                           "channel_id": channel, "message_ordinal": ordinal,
                           "header_stamp_ns": stamp, "image_sha256": image_hash,
                           "decoded_pixels_sha256": hashlib.sha256(decoded.tobytes()).hexdigest(),
                           "width": decoded.shape[1], "height": decoded.shape[0]})
    return {"schema": "rosy.mcap-frame-proof/1", "source_session": session.name,
            "metadata_sha256": metadata_hash,
            "bags": bag_hashes, "decoder": {"mcap": version("mcap"),
                                              "mcap_ros2": version("mcap-ros2-support"),
                                              "opencv": cv2.__version__},
            "frames": proved}
