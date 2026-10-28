"""The installed callable and its live managed-owner description share one binding."""
from contextlib import closing
from dataclasses import dataclass
from typing import Callable

from core_common.protocol.schemas import ArmTransferCapability

from .journal_identity import existing_journal_identity
from .managed_transfer_scope import read_scope
from .transfer_object_bindings import TransferObjectBindings


@dataclass(frozen=True)
class InstalledArmTransferFactory:
    create: Callable
    bindings: object
    capability_revision: str
    config_revision: str
    resource_policy_digest: str
    admission: object
    goal_port: object

    def __post_init__(self):
        if not callable(self.create) or not isinstance(self.bindings, TransferObjectBindings):
            raise ValueError("an installed physical transfer callable and bindings are required")

    def __call__(self, grant, recorder):
        return self.create(grant, recorder)

    def describe(self, runner, identity):
        admission, owner = self.admission, self.admission.owner

        def current(_state):
            admission._session()
            if (not runner.enabled or runner.control_admission is not admission
                    or runner.store is not admission.store or owner._control_admission is not admission
                    or runner.phase_runner_factories.get("ARM_TRANSFER") is not self
                    or getattr(self.goal_port, "command_owner", None) is not owner):
                raise PermissionError("transfer factory is not bound to this enabled owner")
            return admission._managed_scope, owner.session_id

        expected_scope, session = owner.run_admission_policy(current)
        catalog = self.bindings.catalog
        if (expected_scope is None or expected_scope.policy_digest != self.resource_policy_digest
                or (runner.workcell_id, runner.instance_id) != (catalog.workcell_id, catalog.instance_id)
                or (owner.config.workcell_id, owner.config.instance_id) != (
                    catalog.workcell_id, catalog.instance_id)):
            raise PermissionError("installed transfer scope or policy changed")
        with closing(runner.store._connect()) as connection:
            connection.execute("BEGIN")
            scope = read_scope(connection)
            journal = existing_journal_identity(connection)
        if (scope != expected_scope or journal is None or not identity
                or identity.get("journal_id") != journal
                or owner.run_admission_policy(current) != (scope, session)):
            raise PermissionError("canonical owner journal or managed identity changed")
        return ArmTransferCapability(action_kind="ARM_TRANSFER", control_mode="fleet_managed",
            workcell_id=catalog.workcell_id, instance_id=catalog.instance_id,
            journal_id=journal, owner_session_id=session, catalog_digest=catalog.digest,
            bindings_digest=self.bindings.revision, resource_policy_digest=self.resource_policy_digest,
            capability_revision=self.capability_revision, config_revision=self.config_revision)
