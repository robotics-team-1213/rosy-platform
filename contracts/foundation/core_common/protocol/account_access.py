"""D-757 resource grants and Ed25519 access JWTs; no network or role inheritance."""
from __future__ import annotations

import time
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

CAPABILITIES = {
    'site': frozenset({'accounts.manage', 'fleet.read', 'fleet.operate', 'fleet.policy',
                       'camera.manage', 'games.operate', 'vault.read', 'vault.operate', 'vault.manage'}),
    'robot': frozenset({'robot.read', 'robot.operate', 'robot.admin'}),
    'project': frozenset({'learning.view', 'learning.edit', 'learning.approve',
                          'learning.manage', 'learning.import', 'learning.publish'}),
}
RESOURCE_PATTERN = r'^(site|robot|project):[A-Za-z0-9._-]{1,96}$'
ACCESS_TTL_S = 300


class AccessRejected(ValueError):
    """Public failure with no token/key material in the error."""


class AccountGrant(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    resource: str = Field(pattern=RESOURCE_PATTERN)
    capabilities: list[str] = Field(min_length=1, max_length=16)

    @model_validator(mode='after')
    def valid_capabilities(self):
        allowed = CAPABILITIES[self.resource.split(':', 1)[0]]
        if len(set(self.capabilities)) != len(self.capabilities) or not set(self.capabilities) <= allowed:
            raise ValueError('invalid capabilities for resource')
        return self


class AccountAccess(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    iss: str = Field(pattern=r'^https://[^\s?#]+$', max_length=512)
    aud: str = Field(pattern=RESOURCE_PATTERN)
    sub: str = Field(pattern=r'^[A-Za-z0-9._-]{1,128}$')
    sid: str = Field(pattern=r'^[A-Za-z0-9._-]{1,128}$')
    jti: str = Field(pattern=r'^[A-Za-z0-9._-]{16,128}$')
    rev: StrictInt = Field(ge=1)
    iat: StrictInt = Field(ge=0)
    exp: StrictInt = Field(ge=1)
    grants: list[AccountGrant] = Field(min_length=1, max_length=16)

    @model_validator(mode='after')
    def bounded(self):
        if not 0 < self.exp - self.iat <= ACCESS_TTL_S:
            raise ValueError('access lifetime exceeds contract')
        if any(grant.resource != self.aud for grant in self.grants):
            raise ValueError('grant audience mismatch')
        return self

    def permits(self, resource: str, capability: str) -> bool:
        return resource == self.aud and any(
            grant.resource == resource and capability in grant.capabilities for grant in self.grants)


def sign_access(claims: Mapping, private_key: bytes, *, key_id: str) -> str:
    from joserfc import jwt
    from joserfc.jwk import OKPKey
    from joserfc.errors import JoseError
    record = AccountAccess.model_validate(dict(claims))
    if not isinstance(key_id, str) or not key_id or len(key_id) > 128:
        raise AccessRejected('invalid signing key id')
    try:
        key = OKPKey.import_key(private_key)
        if key.curve_name != 'Ed25519':
            raise AccessRejected('invalid signing key')
        return jwt.encode({'alg': 'Ed25519', 'typ': 'at+jwt', 'kid': key_id},
                          record.model_dump(), key, algorithms=['Ed25519'])
    except (JoseError, ValueError, TypeError):
        raise AccessRejected('access signing failed') from None


def verify_access(token: str, public_keys: Mapping[str, bytes], *, issuer: str,
                  audience: str, now: float | None = None) -> AccountAccess:
    from joserfc import jwt
    from joserfc.jwk import OKPKey, KeySet
    from joserfc.errors import JoseError
    if not isinstance(token, str) or len(token) > 16384 or not public_keys:
        raise AccessRejected('invalid access token')
    try:
        keys = []
        for kid, pem in public_keys.items():
            key = OKPKey.import_key(pem, parameters={'kid': kid})
            if key.curve_name != 'Ed25519' or key.is_private:
                raise AccessRejected('invalid verification key')
            keys.append(key)
        decoded = jwt.decode(token, KeySet(keys), algorithms=['Ed25519'])
        if (set(decoded.header) != {'alg', 'typ', 'kid'} or decoded.header['typ'] != 'at+jwt'
                or decoded.header['kid'] not in public_keys):
            raise AccessRejected('invalid access header')
        result = AccountAccess.model_validate(decoded.claims)
        stamp = time.time() if now is None else now
        if (result.iss != issuer or result.aud != audience
                or not result.iat <= stamp < result.exp):
            raise AccessRejected('access expired or outside scope')
        return result
    except (JoseError, ValueError, TypeError, KeyError):
        raise AccessRejected('invalid access token') from None
