"""D-755 actionless-media provenance; eligibility is not execution admission."""
import re

from .artifacts import _base, _fields, _hash, _refs, _text


def _choice(value, choices):
    if not isinstance(value, str) or value not in choices.split():
        raise ValueError(f"expected one of: {choices}")


def _validate(doc, root):
    value = _base(doc, "rosy.media-manifest/1",
                  "profile media_id project_id media_kind source files labels rights")
    if value["profile"] != "actionless_media_v1":
        raise ValueError("unsupported media profile")
    for key in ("media_id", "project_id"):
        _text(value[key])
    _choice(value["media_kind"], "image video unknown")
    source = value["source"]
    _fields(source, "kind capture_session source_group upstream parents")
    _choice(source["kind"], "sim real external_unknown")
    for key in ("capture_session", "source_group"):
        if source[key] is not None:
            _text(source[key])
    upstream = source["upstream"]
    if upstream is not None:
        _fields(upstream, "provider repo_type repo_id revision")
        for key in ("provider", "repo_id"):
            _text(upstream[key])
        _choice(upstream["repo_type"], "dataset")
        if not isinstance(upstream["revision"], str) or not re.fullmatch(
                r"[0-9a-f]{40}|[0-9a-f]{64}", upstream["revision"]):
            raise ValueError("immutable upstream commit required")
    parents = source["parents"]
    if not isinstance(parents, list):
        raise ValueError("parent revision list required")
    for parent in parents:
        _hash(parent)
    if len(parents) != len(set(parents)):
        raise ValueError("unique parent revisions required")
    _refs(value["files"], None)
    labels = value["labels"]
    _fields(labels, "ontology_revision semantic_ids origin status author reviewer evidence")
    _choice(labels["origin"], "none human ai")
    _choice(labels["status"], "unreviewed draft approved rejected")
    if labels["ontology_revision"] is not None:
        _hash(labels["ontology_revision"])
    for key in ("author", "reviewer"):
        if labels[key] is not None:
            _text(labels[key])
    if not isinstance(labels["semantic_ids"], list):
        raise ValueError("semantic identifier list required")
    for semantic in labels["semantic_ids"]:
        _text(semantic)
    if len(labels["semantic_ids"]) != len(set(labels["semantic_ids"])):
        raise ValueError("unique semantic identifiers required")
    _refs(labels["evidence"], None, empty=True)
    if labels["origin"] == "none" and (labels["status"] != "unreviewed"
            or labels["semantic_ids"] or labels["author"] is not None
            or labels["reviewer"] is not None or labels["evidence"]):
        raise ValueError("absent labels cannot carry an approval or author")
    if labels["status"] == "approved" and any(not labels[key] for key in (
            "ontology_revision", "author", "reviewer", "evidence")):
        raise ValueError("label approval requires ontology, author, reviewer and evidence")
    rights = value["rights"]
    _fields(rights, "license evidence view train infer share")
    if rights["license"] is not None:
        _text(rights["license"])
    for key in ("view", "train", "infer", "share"):
        _choice(rights[key], "allowed denied unknown")
    _refs(rights["evidence"], None, empty=True)
    if "allowed" in (rights[key] for key in ("view", "train", "infer", "share")):
        if not rights["license"] or not rights["evidence"]:
            raise ValueError("allowed rights require license and durable evidence")
    _refs(value["files"] + labels["evidence"] + rights["evidence"], root)
    return value


def validate_media(doc, *, root=None, parents=None):
    """Verify a sealed sidecar and its parent closure without altering originals.

    ``root`` verifies this sidecar's bytes. Parent documents retain their sealed
    provenance; their original files can reside in another immutable artifact.
    """
    value = _validate(doc, root)
    if parents is not None and not isinstance(parents, list):
        raise ValueError("parent manifests must be a list")
    ancestors = {}
    for parent in parents or []:
        checked = _validate(parent, None)
        ancestors[checked["revision"]] = checked
    pending, seen = [value], set()
    while pending:
        child = pending.pop()
        if child["revision"] in seen:
            continue
        seen.add(child["revision"])
        for revision in child["source"]["parents"]:
            parent = ancestors.get(revision)
            if parent is None:
                raise ValueError("verified parent manifest required")
            if parent["project_id"] != child["project_id"]:
                raise ValueError("parent must belong to the same project")
            if (not child["source"]["source_group"] or child["source"]["source_group"]
                    != parent["source"]["source_group"]):
                raise ValueError("derived media must preserve its source group")
            pending.append(parent)
    return value


def media_eligibility(doc, *, root=None, parents=None):
    """Return curation prerequisites, never training quality or motion approval."""
    value = validate_media(doc, root=root, parents=parents)
    rights = value["rights"]
    result = {}
    for use, permission in (("view", "view"), ("perception", "train"),
                            ("video_understanding", "train"), ("inference", "infer"),
                            ("external_share", "share")):
        reasons, blocked = [], False
        for key in dict.fromkeys(("view", permission)):
            if rights[key] != "allowed":
                reasons.append(f"{key}_rights_{rights[key]}")
                blocked |= rights[key] == "denied"
        if use in {"perception", "video_understanding", "inference"}:
            if value["media_kind"] == "unknown":
                reasons.append("media_kind_unknown")
        if permission == "train":
            if value["labels"]["status"] != "approved":
                reasons.append("labels_not_human_approved")
                blocked |= value["labels"]["status"] == "rejected"
            if not value["source"]["source_group"]:
                reasons.append("source_group_unknown")
        if use == "video_understanding" and value["media_kind"] == "image":
            reasons.append("video_required")
            blocked = True
        result[use] = {"status": "blocked" if blocked else "hold" if reasons else "eligible",
                       "reasons": reasons}
    result["imitation_learning"] = {"status": "blocked", "reasons": ["aligned_state_action_absent"]}
    return result
