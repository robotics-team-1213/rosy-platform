"""Internal simulation proposal/approval store; no dispatcher or device writer.

The installed snapshot and capability observations come from host composition,
never application bodies. HTTP authentication and live SDK reads are composed
separately. All durable writes use the existing Fleet DB and claim transaction.
"""
from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
import time
from typing import Annotated
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core_common.protocol.arm_transfer import ArmTransferCapability
from core_common.protocol.arm_transfer_jobs import ArmTransferRequest as PhysicalTransferRequest
from core_common.protocol.arm_transfer_preflight import ArmPhysicalRef
from .cell_job_store import CellJobStore
from .dispatch_admission import reserve
from core_common.resource_keys import normalize_resources
from .mission_store import MissionConflict, _json, _nonempty
from .physical_transfer_evidence import PhysicalTransferPolicy
from .site_auth import SitePrincipal


class TransferInstallation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, revalidate_instances="always")
    policy: PhysicalTransferPolicy
    source: ArmPhysicalRef
    target: ArmPhysicalRef
    capabilities: Annotated[tuple[ArmTransferCapability, ...], Field(min_length=1, max_length=32)]

    @model_validator(mode="after")
    def _bindings(self):
        scopes = {(p.workcell_id, p.instance_id) for p in self.policy.participants}
        caps = {(c.workcell_id, c.instance_id): c for c in self.capabilities}
        if set(caps) != scopes or len(caps) != len(self.capabilities) or self.source == self.target:
            raise ValueError("installation must bind exactly all participants and distinct locations")
        primary = caps[self.policy.primary]
        if (any(c.resource_policy_digest != self.policy.digest for c in self.capabilities)
                or primary.catalog_digest != self.policy.catalog_digest
                or primary.bindings_digest != self.policy.bindings_digest):
            raise ValueError("installation capabilities do not match the physical policy")
        return self


def _principal(principal, *, propose=False, operator=False):
    if (not isinstance(principal, SitePrincipal) or principal.password_change_required
            or principal.principal_id == "site-console"):
        raise PermissionError("a configured named principal is required")
    _nonempty("principal_id", principal.principal_id, limit=96)
    if operator:
        allowed = principal.role == "operator" and principal.permits_site("fleet.operate", {"operator"})
    elif propose:
        allowed = principal.role in {"operator", "service"} and principal.permits_site("fleet.operate", {"operator", "service"})
    else:
        allowed = principal.permits_site("fleet.read", {"operator", "service", "viewer"})
    if not allowed:
        raise PermissionError("principal is not permitted to access this physical operation")
    return principal.principal_id


def _matches(request, installed):
    policy = installed.policy
    return ((request.workcell_id, request.instance_id) == policy.primary and request.object_ref == policy.object_ref
            and request.source == installed.source and request.target == installed.target)


class PhysicalTransferStore:
    def __init__(self, path, *, installation, deployment_profile, clock_ns=time.time_ns):
        if deployment_profile != "simulation" or not Path(path).is_file():
            raise ValueError("physical transfers require an existing simulation Fleet journal")
        self.installation = TransferInstallation.model_validate(installation)
        expected = {
            "fleet_tasks": ("task_id", {"task_id"}),
            "fleet_missions": ("mission_id", {"mission_id"}),
            "fleet_dispatch_control": ("control_id", {"control_id", "authority_epoch", "generation", "dispatch_enabled"}),
            "fleet_action_claims": ("resource_key", {"resource_key", "owner_kind", "owner_id", "generation", "phase"}),
        }
        try:
            with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as connection:
                for table, (primary, required) in expected.items():
                    columns = list(connection.execute(f'PRAGMA table_info("{table}")'))
                    if (not required.issubset({c[1] for c in columns})
                            or [c[1] for c in columns if c[5]] != [primary]):
                        raise ValueError("an initialized Fleet journal and exclusive claim schema are required")
                if connection.execute("SELECT 1 FROM fleet_dispatch_control WHERE control_id=1").fetchone() is None:
                    raise ValueError("an initialized Fleet journal control row is required")
        except sqlite3.Error as exc:
            raise ValueError("an initialized Fleet journal is required") from exc
        self._clock_ns = clock_ns
        # Shared initializer owns the version guard and all schema changes atomically.
        self._journal = CellJobStore(path)

    def _now_ns(self):
        value = self._clock_ns()
        if type(value) is not int or not 0 <= value < 2**63:
            raise ValueError("server time must be UTC integer nanoseconds")
        return value

    def _document(self, request):
        installed = self.installation.model_dump(mode="json")
        installed["capabilities"].sort(key=lambda c: (c["workcell_id"], c["instance_id"]))
        return _json({"request": request.model_dump(mode="json"), "installation": installed})

    @staticmethod
    def _read(connection, mission_id):
        row = connection.execute("SELECT j.*,a.approved_by,a.approved_at_ns,a.claims_acquired_at_ns "
            "FROM fleet_cell_jobs j LEFT JOIN fleet_physical_transfer_approvals a USING(mission_id) "
            "WHERE j.mission_id=? AND j.provenance_kind='physical'", (mission_id,)).fetchone()
        if row is None:
            return None
        result = {key: row[key] for key in ("mission_id", "proposal_principal_id", "request_key", "request_digest",
            "status", "authority_epoch", "dispatch_generation", "reason", "approved_by", "approved_at_ns", "claims_acquired_at_ns")}
        document = json.loads(row["job_json"])
        if not isinstance(document, dict) or set(document) != {"request", "installation"}:
            raise ValueError("physical snapshot has unsupported fields")
        request = PhysicalTransferRequest.model_validate(document["request"])
        installed = TransferInstallation.model_validate_json(_json(document["installation"]))
        if (not _matches(request, installed) or (request.workcell_id, request.instance_id) != (row["workcell_id"], row["instance_id"])
                or sha256(_json(request.model_dump(mode="json")).encode()).hexdigest() != row["request_digest"]
                or _json(installed.policy.resources) != row["resources_json"]):
            raise ValueError("physical snapshot does not match its journal binding")
        result["request"] = request.model_dump(mode="json")
        result["installation"] = installed.model_dump(mode="json")
        result["proposal_digest"] = sha256(row["job_json"].encode()).hexdigest()
        result["resources"] = json.loads(row["resources_json"])
        return result

    def get(self, mission_id, *, principal):
        actor = _principal(principal)
        with closing(self._journal._connect()) as connection:
            result = self._read(connection, mission_id)
        if result is not None and result["proposal_principal_id"] != actor:
            _principal(principal, operator=True)
        return result

    def get_by_request_key(self, request_key, *, principal):
        actor = _principal(principal)
        key = _nonempty("request_key", request_key, limit=160)
        with closing(self._journal._connect()) as connection:
            row = connection.execute("SELECT mission_id FROM fleet_cell_jobs WHERE provenance_kind='physical' "
                                     "AND proposal_principal_id=? AND request_key=?", (actor, key)).fetchone()
            return self._read(connection, row[0]) if row is not None else None

    def create(self, *, principal, request_key, request):
        with closing(self._journal._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            result = self._create(connection, principal=principal, request_key=request_key, request=request)
            connection.commit()
            return result

    def _create(self, connection, *, principal, request_key, request):
        actor = _principal(principal, propose=True)
        if actor == self.installation.policy.producer_id:
            raise PermissionError("physical observer cannot propose an operation")
        key = _nonempty("request_key", request_key, limit=160)
        request = PhysicalTransferRequest.model_validate(request)
        digest = sha256(_json(request.model_dump(mode="json")).encode()).hexdigest()
        prior = connection.execute("SELECT mission_id,request_digest FROM fleet_cell_jobs "
            "WHERE provenance_kind='physical' AND proposal_principal_id=? AND request_key=?", (actor, key)).fetchone()
        if prior is not None:
            if prior["request_digest"] != digest:
                raise MissionConflict("physical request key was reused with a different request")
            return self._read(connection, prior["mission_id"])
        installed, policy = self.installation, self.installation.policy
        if not _matches(request, installed):
            raise MissionConflict("physical references are not in the installed transfer profile")
        mission_id = "physical-" + uuid4().hex
        timestamp = datetime.fromtimestamp(self._now_ns() / 1e9, timezone.utc).isoformat()
        connection.execute("""INSERT INTO fleet_cell_jobs(mission_id,proposal_principal_id,request_key,request_digest,
            workcell_id,instance_id,job_json,resources_json,ledger_markers_json,status,created_at,updated_at,provenance_kind)
            VALUES(?,?,?,?,?,?,?,?,'[]','PROPOSED',?,?,'physical')""",
            (mission_id, actor, key, digest, request.workcell_id, request.instance_id, self._document(request),
             _json(policy.resources), timestamp, timestamp))
        self._journal._event(connection, mission_id, None, "PHYSICAL_TRANSFER_PROPOSED", actor, {"request_digest": digest})
        return self._read(connection, mission_id)

    def _check_capabilities(self, capabilities, observed_at_ns, now_ns):
        if (type(observed_at_ns) is not int or observed_at_ns < 0 or observed_at_ns > now_ns
                or now_ns - observed_at_ns > self.installation.policy.max_age_ns):
            raise MissionConflict("physical capability snapshot is stale or future")
        try:
            current = tuple(ArmTransferCapability.model_validate(c) for c in capabilities)
        except (ValueError, TypeError) as exc:
            raise MissionConflict("physical capability snapshot is invalid") from exc
        ordered = lambda values: sorted(values, key=lambda c: (c.workcell_id, c.instance_id))
        if ordered(current) != ordered(self.installation.capabilities):
            raise MissionConflict("a physical owner capability or identity changed")

    def admit(self, mission_id, *, principal, expected_proposal_digest, expected_generation,
              capabilities, capabilities_observed_at_ns):
        with closing(self._journal._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            result = self._admit(connection, mission_id, principal=principal,
                expected_proposal_digest=expected_proposal_digest, expected_generation=expected_generation,
                capabilities=capabilities, capabilities_observed_at_ns=capabilities_observed_at_ns)
            connection.commit()
            return result

    def _admit(self, connection, mission_id, *, principal, expected_proposal_digest, expected_generation,
               capabilities, capabilities_observed_at_ns):
        actor = _principal(principal, operator=True)
        if actor == self.installation.policy.producer_id:
            raise PermissionError("physical observer cannot approve an operation")
        if (not isinstance(expected_proposal_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_proposal_digest)
                or type(expected_generation) is not int or expected_generation < 0):
            raise ValueError("exact proposal digest and dispatch generation are required")
        row = connection.execute("SELECT * FROM fleet_cell_jobs WHERE mission_id=? AND provenance_kind='physical'",
                                 (mission_id,)).fetchone()
        if row is None:
            raise KeyError(mission_id)
        if actor == row["proposal_principal_id"]:
            raise PermissionError("physical proposer cannot approve its own operation")
        result = self._read(connection, mission_id)
        request = PhysicalTransferRequest.model_validate(result["request"])
        if (result["proposal_digest"] != expected_proposal_digest or row["job_json"] != self._document(request)
                or row["resources_json"] != _json(self.installation.policy.resources)):
            raise MissionConflict("physical proposal or installed snapshot changed")
        control = connection.execute("SELECT * FROM fleet_dispatch_control WHERE control_id=1").fetchone()
        if control is None or not control["dispatch_enabled"] or control["generation"] != expected_generation:
            raise MissionConflict("physical dispatch generation is closed or changed")
        checked_at = self._now_ns()
        self._check_capabilities(capabilities, capabilities_observed_at_ns, checked_at)
        if row["status"] == "READY" and result["approved_by"] == actor:
            owned = connection.execute("SELECT resource_key,generation,phase FROM fleet_action_claims "
                "WHERE owner_kind='mission' AND owner_id=?", (mission_id,)).fetchall()
            expected = {key for _, _, key in normalize_resources(self.installation.policy.resources)}
            if (row["authority_epoch"] == control["authority_epoch"] and row["dispatch_generation"] == expected_generation
                    and {c["resource_key"] for c in owned} == expected
                    and all(c["generation"] == expected_generation and c["phase"] == "CLAIMED" for c in owned)):
                return result
        if row["status"] != "PROPOSED":
            raise MissionConflict("physical operation was already admitted or held")
        if not reserve(connection, owner_kind="mission", owner_id=mission_id, generation=expected_generation,
                       resources=self.installation.policy.resources, phase="CLAIMED"):
            raise MissionConflict("physical resource claim conflicts with another operation")
        boundary = self._now_ns()  # Capture after reservation; preconditions must be observed later.
        if boundary < checked_at:
            raise MissionConflict("server clock moved backwards during physical reservation")
        self._check_capabilities(capabilities, capabilities_observed_at_ns, boundary)
        connection.execute("INSERT INTO fleet_physical_transfer_approvals VALUES(?,?,?,?,?,?,?)",
            (mission_id, expected_proposal_digest, actor, boundary, boundary, control["authority_epoch"], expected_generation))
        connection.execute("UPDATE fleet_cell_jobs SET status='READY',authority_epoch=?,dispatch_generation=?,updated_at=? "
                           "WHERE mission_id=?", (control["authority_epoch"], expected_generation,
                           datetime.fromtimestamp(boundary / 1e9, timezone.utc).isoformat(), mission_id))
        self._journal._event(connection, mission_id, None, "PHYSICAL_TRANSFER_ADMITTED", actor,
            {"proposal_digest": expected_proposal_digest, "authority_epoch": control["authority_epoch"],
             "dispatch_generation": expected_generation, "claims_acquired_at_ns": boundary})
        return self._read(connection, mission_id)
