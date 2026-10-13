"""D-619: observed situations and advisory directions, without execution authority."""
from collections.abc import Mapping

VERSION = "situation-v1"
DOMAINS = ("mobility", "manipulation")
TYPES = ("geometry", "obstruction", "visibility_limited", "target_missing", "target_misaligned",
         "resource_conflict", "action_unconfirmed", "unknown")
DIRECTIONS = ("hold", "reobserve", "recover", "replan", "human_review", "continue")


def model_assessment_schema(sources):
    """The same vocabulary and bounds for constrained model output."""
    text = {"type": "string", "minLength": 1, "maxLength": 300}
    return {"type": "object", "additionalProperties": False,
            "required": ["type", "direction", "observations", "uncertainties"], "properties": {
                "type": {"type": "string", "enum": list(TYPES)},
                "direction": {"type": "string", "enum": list(DIRECTIONS)},
                "observations": {"type": "object", "additionalProperties": False,
                                 "required": list(sources), "properties": {source: text for source in sources}},
                "uncertainties": {"type": "array", "maxItems": 8, "items": text}}}


def _text(value, limit=300):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError("bounded nonempty observation text required")
    return value.strip()


def validate_assessment(value, views):
    """Validate model-origin metadata; even a correct shape is still unverified."""
    keys = {"version", "domain", "type", "direction", "observations", "uncertainties", "verification"}
    if (not isinstance(value, Mapping) or set(value) != keys or value["version"] != VERSION
            or value["domain"] not in DOMAINS or value["type"] not in TYPES
            or value["direction"] not in DIRECTIONS or value["verification"] != "unverified"):
        raise ValueError("unsupported situation assessment or model verification claim")
    observations = value["observations"]
    if not isinstance(observations, list) or not 1 <= len(observations) <= 8 or not isinstance(views, Mapping):
        raise ValueError("frame-bound observations required")
    sources = set()
    for observation in observations:
        if not isinstance(observation, Mapping) or set(observation) != {"source", "frame_id", "description"}:
            raise ValueError("invalid observation fields")
        source = _text(observation["source"], 96)
        frame = _text(observation["frame_id"], 128)
        if (source in sources or source not in views or not isinstance(views[source], Mapping)
                or frame != views[source].get("frame_id")):
            raise ValueError("observation does not match an input frame")
        sources.add(source)
        _text(observation["description"])
    if sources != set(views):
        raise ValueError("each supplied view needs its own observation")
    uncertainties = value["uncertainties"]
    if not isinstance(uncertainties, list) or len(uncertainties) > 8:
        raise ValueError("bounded uncertainty list required")
    for uncertainty in uncertainties:
        _text(uncertainty)


def build_assessment(answer, domain, views):
    """Bind the model's descriptions to caller-owned frame IDs, never model-supplied IDs."""
    if not isinstance(answer, Mapping) or set(answer) != {"type", "direction", "observations", "uncertainties"}:
        raise ValueError("structured situation answer required")
    if not isinstance(answer["observations"], Mapping) or not isinstance(views, Mapping):
        raise ValueError("source descriptions and input views required")
    observations = []
    for source, description in answer["observations"].items():
        if source not in views or not isinstance(views[source], Mapping):
            raise ValueError("unknown observation source")
        observations.append({"source": source, "frame_id": views[source].get("frame_id"),
                             "description": description})
    value = {"version": VERSION, "domain": domain, "type": answer["type"], "direction": answer["direction"],
             "observations": observations, "uncertainties": answer["uncertainties"], "verification": "unverified"}
    validate_assessment(value, views)
    return value
