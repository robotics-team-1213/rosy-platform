"""D-418 로봇 SSH 접속 wire 모델 (API Ref §5.8, v1.89 additive).

administrator 전용 /api/v1/host/ssh/... 의 본문과 응답. CORE 는 이 모양을 검사한
뒤 root rosy-ssh-access 에 넘기고, 그 도우미가 같은 규칙을 따로 다시 검사한다.
schemas.py 의 크기 한도(D-766)를 지키기 위해 같은 내용을 그대로 옮겼고,
정식 수출은 schemas.py 가 계속한다.
"""
import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

SSH_LABEL_PATTERN = r"^[a-z0-9][a-z0-9._:-]{0,47}$"
SSH_KEY_TYPES = ("ssh-ed25519", "sk-ssh-ed25519@openssh.com",
                 "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521")
SSH_TIME_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
SSH_MAX_KEYS = 32
_SSH_PUBLIC_KEY = re.compile(r"^(?P<type>[a-z0-9@.-]+) [A-Za-z0-9+/]+={0,2}(?: [!-~ ]{1,100})?$")


class SshKeyAddRequest(BaseModel):
    """POST /host/ssh/keys. 선택 항목·authorized_keys 옵션은 받지 않는다."""

    model_config = ConfigDict(extra="forbid", strict=True)

    public_key: str = Field(min_length=1, max_length=1200)
    label: str = Field(pattern=SSH_LABEL_PATTERN)
    expires_days: int = Field(ge=1, le=365)

    @field_validator("public_key")
    @classmethod
    def _one_allowed_line(cls, value: str) -> str:
        match = _SSH_PUBLIC_KEY.fullmatch(value.strip())
        if match is None or match["type"] not in SSH_KEY_TYPES:
            raise ValueError(f"one OpenSSH public key line of {', '.join(SSH_KEY_TYPES)}")
        return value.strip()


class SshKeyAdded(BaseModel):
    label: str = Field(pattern=SSH_LABEL_PATTERN)
    fingerprint: str = Field(pattern=r"^SHA256:[A-Za-z0-9+/]{43}$")
    expires_at: str = Field(pattern=SSH_TIME_PATTERN)


class SshKeyInfo(BaseModel):
    label: str = Field(pattern=SSH_LABEL_PATTERN)
    type: Literal["ssh-ed25519", "sk-ssh-ed25519@openssh.com",
                  "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521"]
    fingerprint: str = Field(pattern=r"^SHA256:[A-Za-z0-9+/]{43}$")
    added_at: str = Field(pattern=SSH_TIME_PATTERN)
    expires_at: str = Field(pattern=SSH_TIME_PATTERN)
    added_by: str = Field(max_length=128)


class SshKeyList(BaseModel):
    keys: list[SshKeyInfo] = Field(max_length=SSH_MAX_KEYS)


class SshHostKeys(BaseModel):
    hostname: str
    host_keys: list[str]


class SshPasswordRequest(BaseModel):
    """POST /host/ssh/password. 분 단위, 1..60."""

    model_config = ConfigDict(extra="forbid", strict=True)

    minutes: int = Field(ge=1, le=60)


class SshPasswordIssued(BaseModel):
    user: Literal["rosy"]
    password: str = Field(pattern=r"^rosy-[a-hjkmnp-z2-9]{4}-[a-hjkmnp-z2-9]{4}-[a-hjkmnp-z2-9]{4}$")
    expires_at: str = Field(pattern=SSH_TIME_PATTERN)


class SshPasswordStatus(BaseModel):
    enabled: bool
    expires_at: Optional[str] = Field(default=None, pattern=SSH_TIME_PATTERN)
    #: usermod could not lock the password; sshd refuses it by a drop-in until the retry locks it.
    lock_pending: bool = False
