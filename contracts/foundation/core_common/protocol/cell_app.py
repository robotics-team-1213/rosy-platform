"""Fleet Cell workspace requests (API Ref v1.90); no robot control authority."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CellAppDocumentSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    document: dict[str, Any]
    expected_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class CellAppCompileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    recipe_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    recipe_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    cell_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    cell_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class CellAppProposalRequest(CellAppCompileRequest):
    request_key: str = Field(min_length=1, max_length=160)
    workcell_id: str = Field(min_length=1, max_length=96)
    instance_id: str = Field(min_length=1, max_length=96)

    @field_validator("request_key", "workcell_id", "instance_id")
    @classmethod
    def _trimmed_identifier(cls, value):
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("identifier must be trimmed and contain no control characters")
        return value
