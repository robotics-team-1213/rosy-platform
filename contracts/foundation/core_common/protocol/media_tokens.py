"""Internal D-789 media delegation signatures; never a CORE command credential."""

import time

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


class MediaTokenRejected(ValueError):
    pass


class MediaClaims(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)
    # D-801: a site may issue READ-only grants (iss == aud == site:<id>); robots issue their own.
    iss: str = Field(pattern=r'^(robot|site):[A-Za-z0-9._-]{1,96}$')
    aud: str = Field(pattern=r'^site:[A-Za-z0-9._-]{1,96}$')
    sub: str = Field(min_length=1, max_length=128)
    jti: str = Field(pattern=r'^[a-f0-9]{32}$')
    robot_id: str = Field(pattern=r'^[A-Za-z0-9._-]{1,96}$')
    path: str = Field(max_length=128)
    action: str = Field(pattern=r'^(read|publish)$')
    iat: StrictInt = Field(ge=0)
    exp: StrictInt = Field(ge=1)

    @model_validator(mode='after')
    def bounded(self):
        issuer_ok = (self.iss == 'robot:' + self.robot_id
                     or (self.iss == self.aud and self.action == 'read'))
        if (not 0 < self.exp - self.iat <= 60 or not issuer_ok
                or self.path != f'robots/{self.robot_id}/front'):
            raise ValueError('media delegation outside scope')
        return self


def sign_media(claims, private_key, key_id):
    from joserfc import jwt
    from joserfc.jwk import OKPKey
    from joserfc.errors import JoseError
    try:
        record = MediaClaims.model_validate(claims)
        if not isinstance(key_id, str) or not 1 <= len(key_id) <= 128:
            raise ValueError()
        key = OKPKey.import_key(private_key)
        if key.curve_name != 'Ed25519' or not key.is_private:
            raise ValueError()
        return jwt.encode({'alg': 'Ed25519', 'typ': 'rosy-media+jwt', 'kid': key_id},
                          record.model_dump(), key, algorithms=['Ed25519'])
    except (JoseError, TypeError, ValueError):
        raise MediaTokenRejected('media signing failed') from None


def public_media_key(private_key):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = serialization.load_pem_private_key(private_key, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise MediaTokenRejected('invalid media signing key')
    return key.public_key().public_bytes(serialization.Encoding.PEM,
                                         serialization.PublicFormat.SubjectPublicKeyInfo)


def verify_media(token, public_keys, *, robot_id, audience, now=None):
    from joserfc import jwt
    from joserfc.jwk import KeySet, OKPKey
    from joserfc.errors import JoseError
    try:
        if not isinstance(token, str) or len(token) > 4096 or not public_keys:
            raise ValueError()
        keys = []
        for kid, pem in public_keys.items():
            key = OKPKey.import_key(pem, parameters={'kid': kid})
            if key.curve_name != 'Ed25519' or key.is_private:
                raise ValueError()
            keys.append(key)
        result = jwt.decode(token, KeySet(keys), algorithms=['Ed25519'])
        if (set(result.header) != {'alg', 'typ', 'kid'}
                or result.header['typ'] != 'rosy-media+jwt'
                or result.header['kid'] not in public_keys):
            raise ValueError()
        claims = MediaClaims.model_validate(result.claims)
        stamp = time.time() if now is None else now
        if (claims.robot_id != robot_id or claims.aud != audience
                or not claims.iat <= stamp < claims.exp):
            raise ValueError()
        return claims
    except (JoseError, TypeError, ValueError, KeyError):
        raise MediaTokenRejected('media token invalid or outside scope') from None
