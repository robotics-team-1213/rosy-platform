"""MCAP review imports keep source identity and never inherit video decisions."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcap_ros2")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dataset"))
from review_app import ReviewStore  # noqa: E402
import review_evidence  # noqa: E402
import review_ingest  # noqa: E402
from test_mcap_proof import _fixture  # noqa: E402
from mcap_proof import prove_frames  # noqa: E402
from test_review_cycle import CLASSES  # noqa: E402
from test_review_app import open_store  # noqa: E402


def _catalog(tmp_path):
    session, row = _fixture(tmp_path)
    proof = prove_frames(session, [row], tmp_path)
    folder = tmp_path / "catalog"
    folder.mkdir()
    classes = folder / "classes.yaml"
    classes.write_bytes(CLASSES)
    catalog = folder / "verified-inputs.jsonl"
    catalog.write_text(json.dumps({"source_kind": "mcap", "source_session": session.name,
                                   "capture_group": "heldout-group", "fixed_eval_overlap": True,
                                   "image": str(row["image"]),
                                   "image_sha256": hashlib.sha256(row["image"].read_bytes()).hexdigest(),
                                   "width": 6, "height": 4,
                                    "mcap": {"session_dir": str(session),
                                            "metadata_sha256": proof["metadata_sha256"],
                                            "bags": proof["bags"], "decoder": proof["decoder"],
                                            "frame": proof["frames"][0]}}) + "\n")
    return catalog, classes


def test_empty_eval_workspace_imports_only_proven_mcap_as_pending(tmp_path):
    store = ReviewStore(tmp_path / "eval-state", empty_eval=True)
    catalog, classes = _catalog(tmp_path)
    body = {"path": str(catalog), "classes": str(classes)}
    result = review_ingest.import_frames(store, body)
    assert result["added"] == 1
    frame = store.get(0)
    assert frame["status"] == "pending" and frame["source"]["source_kind"] == "mcap"
    assert frame["source"]["mcap"]["frame"]["header_stamp_ns"] == 1_000_000_123
    assert review_evidence.identity(frame["source"]).startswith("mcap:")
    assert review_ingest.import_frames(store, body)["added"] == 0
    assert len(store.list_frames()) == 1


def test_mcap_import_rejects_changed_bag_before_workspace_mutation(tmp_path):
    store = ReviewStore(tmp_path / "eval-state", empty_eval=True)
    catalog, classes = _catalog(tmp_path)
    source = tmp_path / "session" / "bag" / "bag_2.mcap"
    source.write_bytes(source.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="bag hash"):
        review_ingest.import_frames(store, {"path": str(catalog), "classes": str(classes),
                                            "scratch": str(tmp_path)})
    assert store.list_frames() == []


def test_mcap_identity_never_links_same_pixels_to_video_workspace(tmp_path):
    (tmp_path / "video").mkdir()
    video_store = open_store(tmp_path / "video")
    catalog, classes = _catalog(tmp_path)
    with pytest.raises(ValueError, match="separate evaluation workspace"):
        review_ingest.import_frames(video_store, {"path": str(catalog), "classes": str(classes),
                                                  "scratch": str(tmp_path)})
    assert len(video_store.list_frames()) == 2


def test_mcap_ambiguous_log_time_requires_message_ordinal(tmp_path):
    session, row = _fixture(tmp_path, duplicate=True)
    with pytest.raises(ValueError, match="ambiguous"):
        prove_frames(session, [row], tmp_path)
    proof = prove_frames(session, [{**row, "message_ordinal": 0}], tmp_path)
    assert proof["frames"][0]["message_ordinal"] == 0


def test_mcap_import_refuses_auto_mask_draft(tmp_path):
    store = ReviewStore(tmp_path / "eval-state", empty_eval=True)
    catalog, classes = _catalog(tmp_path)
    row = json.loads(catalog.read_text())
    row["mask"] = {"indexed_png": "auto.png", "sha256": "0" * 64,
                   "classes_sha256": "0" * 64}
    catalog.write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="empty pixel mask"):
        review_ingest.import_frames(store, {"path": str(catalog), "classes": str(classes)})
    assert store.list_frames() == []
