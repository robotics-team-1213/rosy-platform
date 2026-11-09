"""D-721 Amendment: a person request is a note for a person near a robot (API Ref, v1.372).

Fleet owns the record and the answer. CORE only holds the open request for its robot so the dashboard and the face
can show it. Nothing here carries motion authority: an answer is a person's statement, never a command, a stop
release or a passed safety check.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core_common.person_request_text import DEFAULT_TTL_S, FACE_TEXT, KINDS, MAX_TTL_S  # noqa: F401

CONTROL = re.compile(r"[\x00-\x1f\x7f]")
ID_PATTERN = r"^[0-9a-f]{32}$"


class PersonRequestBody(BaseModel):
    """What Fleet puts on a robot: ``PUT /api/v1/person-request``."""

    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(pattern=ID_PATTERN)
    kind: Literal["unplug_charger", "plug_charger", "move_robot", "clear_area", "other"]
    text: str = Field(min_length=1, max_length=200)
    why: str = Field(default="", max_length=200)
    ttl_s: float = Field(default=DEFAULT_TTL_S, gt=0, le=MAX_TTL_S, allow_inf_nan=False)


class PersonRequestAnswerBody(BaseModel):
    """A logged-in person's answer at the robot: ``POST /api/v1/person-request/{id}/answer``. Fleet reads it back."""

    model_config = ConfigDict(extra="forbid")
    answer: Literal["done", "cannot"]
