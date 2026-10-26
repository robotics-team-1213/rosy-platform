"""Immutable owner-configured object/geometry correspondence; no admission authority."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from pydantic import TypeAdapter

from core_common.protocol.arm_transfer_preflight import ArmPhysicalRef

from .transfer_motion import GraspGeometry, TransferPlanRejected
from .transfer_preflight import ArmTransferCatalog

_REFERENCE = TypeAdapter(ArmPhysicalRef)


@dataclass(frozen=True)
class TransferObjectBindings:
    """Installation data, used only after a trusted owner explicitly installs it."""

    catalog: ArmTransferCatalog
    objects: Mapping[str, str]
    revision: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.catalog, ArmTransferCatalog):
            raise ValueError("physical object bindings require a catalog")
        if not isinstance(self.objects, Mapping) or not self.objects:
            raise ValueError("object bindings must be a non-empty reference map")
        copied = {}
        for object_ref, geometry_ref in self.objects.items():
            object_ref = _REFERENCE.validate_python(object_ref)
            geometry_ref = _REFERENCE.validate_python(geometry_ref)
            if geometry_ref not in self.catalog.geometries:
                raise ValueError("object geometry is not in the physical catalog")
            copied[object_ref] = geometry_ref
        object.__setattr__(self, "objects", MappingProxyType(copied))
        document = {"schema": "rosy.omx-transfer-object-bindings.v1",
                    "catalog_digest": self.catalog.digest, "objects": copied}
        canonical = json.dumps(document, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False, allow_nan=False).encode("utf-8")
        object.__setattr__(self, "revision", hashlib.sha256(canonical).hexdigest())

    def resolve(self, object_ref: str, *, catalog_digest: str, bindings_digest: str) -> GraspGeometry:
        if catalog_digest != self.catalog.digest:
            raise TransferPlanRejected("CATALOG_MISMATCH", "physical installation catalog changed")
        if bindings_digest != self.revision:
            raise TransferPlanRejected("OBJECT_BINDINGS_MISMATCH", "physical object bindings changed")
        if not isinstance(object_ref, str) or object_ref not in self.objects:
            raise TransferPlanRejected("OBJECT_NOT_BOUND", "physical object has no installed geometry")
        return self.catalog.geometries[self.objects[object_ref]]
