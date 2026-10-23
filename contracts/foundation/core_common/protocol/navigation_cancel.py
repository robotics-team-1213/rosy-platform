"""D-855 exact navigation cancellation; absent support must fail without stopping another goal."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ScopedNavigationCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    expected_boot_id: UUID
    run_id: UUID
    correlation_id: str = Field(strict=True, min_length=1, max_length=128,
                                pattern=r"^[^\x00-\x1f\x7f]+$")
