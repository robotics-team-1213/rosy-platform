"""Compatibility re-export: the rosy.perception.model manifest now lives in core_common.perception_model."""

from core_common.perception_model import (  # noqa: F401
    SCHEMA, NCNN_SCHEMA, NCNN_FAMILIES, TASKS, ROLES, ROAD_SEMANTICS, OBJECT_ROLE, OBJECT_CLASSES,
    LAYOUTS, COLORS, PRECISIONS, MANIFEST_NAME, REVISION_PATTERN, VERSION_PATTERN, ManifestError,
    validate_label_semantic, road_delivery_error, ModelFile, InputSpec, ClassSpec, ModelManifest,
    check_revision, load_manifest, sha256_file, verify_files,
)
