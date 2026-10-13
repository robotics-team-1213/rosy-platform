"""Actionless imports preserve unknowns and cannot become action demonstrations."""
import hashlib
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "contracts/learning/src"))
from rosy.contracts.learning.artifacts import seal
from rosy.contracts.learning.media import media_eligibility, validate_media


def media(tmp_path):
    def ref(name, content):
        (tmp_path / name).write_bytes(content)
        return {"path": name, "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}

    return seal({
        "schema": "rosy.media-manifest/1", "profile": "actionless_media_v1",
        "media_id": "import-1", "project_id": "project-1", "media_kind": "video",
        "source": {"kind": "external_unknown", "capture_session": None,
                   "source_group": "hf-dataset-owner-recording", "parents": [],
                   "upstream": {"provider": "huggingface", "repo_type": "dataset",
                                "repo_id": "owner/recording", "revision": "a" * 40}},
        "files": [ref("video.mp4", b"original video bytes")],
        "labels": {"ontology_revision": "b" * 64, "semantic_ids": ["object.box"],
                   "origin": "human", "status": "approved", "author": "alice",
                   "reviewer": "bob", "evidence": [ref("labels.json", b"approved labels")]},
        "rights": {"license": "test-license", "evidence": [ref("rights.json", b"rights proof")],
                   "view": "allowed", "train": "allowed", "infer": "allowed", "share": "unknown"},
    })


def test_actionless_video_is_not_an_action_demonstration(tmp_path):
    doc = media(tmp_path)
    assert validate_media(doc, root=tmp_path) == doc
    result = media_eligibility(doc, root=tmp_path)
    assert result["perception"]["status"] == "eligible"
    assert result["video_understanding"]["status"] == "eligible"
    assert result["imitation_learning"]["status"] == "blocked"
    assert result["external_share"]["status"] == "hold"
    assert "action" not in doc


@pytest.mark.parametrize("right,use", [("view", "view"), ("train", "perception"),
                                      ("infer", "inference"), ("share", "external_share")])
def test_unknown_or_denied_right_never_qualifies(tmp_path, right, use):
    doc = media(tmp_path)
    for permission, status in [("unknown", "hold"), ("denied", "blocked")]:
        doc["rights"][right] = permission
        assert media_eligibility(seal(doc), root=tmp_path)[use]["status"] == status


def test_ai_draft_requires_human_review_before_training(tmp_path):
    doc = media(tmp_path)
    doc["labels"].update(origin="ai", status="draft", author="model-revision", reviewer=None)
    assert media_eligibility(seal(doc))["perception"]["status"] == "hold"
    doc["labels"].update(status="approved")
    with pytest.raises(ValueError, match="approval"):
        validate_media(seal(doc))
    doc["labels"]["reviewer"] = "bob"
    assert media_eligibility(seal(doc))["perception"]["status"] == "eligible"


@pytest.mark.parametrize("field", ["ontology_revision", "reviewer"])
def test_approval_requires_ontology_and_named_reviewer(tmp_path, field):
    doc = media(tmp_path)
    doc["labels"][field] = None
    with pytest.raises(ValueError, match="approval"):
        validate_media(seal(doc))


def test_rights_allowance_needs_durable_evidence(tmp_path):
    doc = media(tmp_path)
    doc["rights"]["evidence"] = []
    with pytest.raises(ValueError, match="rights"):
        validate_media(seal(doc))


def test_missing_capture_group_holds_training(tmp_path):
    doc = media(tmp_path)
    doc["source"]["source_group"] = None
    result = media_eligibility(seal(doc))
    assert result["perception"]["status"] == "hold"
    assert "source_group_unknown" in result["perception"]["reasons"]


@pytest.mark.parametrize("path", ["../outside.mp4", "C:/video.mp4", "a\\video.mp4", "/video.mp4"])
def test_file_paths_cannot_escape(tmp_path, path):
    doc = media(tmp_path)
    doc["files"][0]["path"] = path
    with pytest.raises(ValueError, match="path"):
        validate_media(seal(doc), root=tmp_path)


def test_tampered_original_or_evidence_rejected(tmp_path):
    doc = media(tmp_path)
    (tmp_path / "labels.json").write_bytes(b"changed label")
    with pytest.raises(ValueError, match="hash/size"):
        validate_media(doc, root=tmp_path)


def test_wire_rejects_unknown_fields_and_mutated_revision(tmp_path):
    doc = media(tmp_path)
    doc["action"] = [0]
    with pytest.raises(ValueError, match="exact fields"):
        validate_media(seal(doc))
    del doc["action"]
    doc["project_id"] = "another-project"
    with pytest.raises(ValueError, match="canonical revision"):
        validate_media(doc)


def test_mutable_upstream_revision_rejected(tmp_path):
    doc = media(tmp_path)
    doc["source"]["upstream"]["revision"] = "main"
    with pytest.raises(ValueError, match="immutable"):
        validate_media(seal(doc))


def test_derived_media_requires_verified_parent_and_same_group(tmp_path):
    original = media(tmp_path)
    derived = media(tmp_path)
    derived["media_id"] = "reencoded"
    derived["source"]["parents"] = [original["revision"]]
    derived = seal(derived)
    with pytest.raises(ValueError, match="parent"):
        validate_media(derived)
    assert validate_media(derived, parents=[original]) == derived
    derived["source"]["source_group"] = "new-group"
    with pytest.raises(ValueError, match="group"):
        validate_media(seal(derived), parents=[original])
