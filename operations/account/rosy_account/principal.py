"""Account identity and explicit capability checks, shared by receivers."""
from dataclasses import dataclass, field
from typing import Mapping, Optional

@dataclass(frozen=True)
class SitePrincipal:
    principal_id: str
    role: str
    password_change_required: bool = False
    password_fingerprint: str = field(default="", compare=False, repr=False)
    account_id: Optional[str] = None
    grants: tuple = ()
    site_resource: Optional[str] = None

    def permits(self, resource: str, capability: str) -> bool:
        return bool(self.account_id) and any(
            scope == resource and capability in capabilities for scope, capabilities in self.grants)

    def permits_site(self, capability: str, legacy_roles=None) -> bool:
        if self.account_id:
            return bool(self.site_resource) and self.permits(self.site_resource, capability)
        # D-793: a users-file grant (policy_admin) adds a capability beside the single legacy role.
        return (legacy_roles is None or self.role in legacy_roles
                or any(scope == "legacy" and capability in caps for scope, caps in self.grants))


def legacy_grants(details: Mapping) -> tuple:
    return (("legacy", ("fleet.policy",)),) if details.get("policy_admin") is True else ()
