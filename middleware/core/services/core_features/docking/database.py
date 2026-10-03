"""core_features.docking.database — 도크 기종/개체 저장소 (DNC-001).

도크는 Waypoint 가 아니다. Waypoint 는 포즈를 담지만 도크는 장치다 — 기종,
스테이징 오프셋, 에이전트 주소, 충전 계약을 함께 갖는다.

기종(`DockType`)과 개체(`DockInstance`)를 나누는 것은 Nav2 의 `dock_plugins`/
`docks` 분리와 같다. 구현은 로봇당 도크 1개를 목표로 하지만, 이 형태를 지금
잡아두면 나중에 풀로 확장할 때 계약을 깨지 않아도 된다.

ROS 무의존. JSON 저장소는 waypoints.json 옆에 둔다 (D-9와 같은 방식).

설계: docs/plans/2026-09-02-docking-station-design.md
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class DockError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class Pose2D(BaseModel):
    x: float = 0.0
    y: float = 0.0
    yaw: float = 0.0


class DockType(BaseModel):
    """도크 기종. 같은 기종의 도크 여럿이 이 설정 하나를 공유한다."""

    name: str
    detector: str                       # 검출기 플러그인 이름 (경계 뒤)
    staging_offset_m: float = 0.7       # 도크 정면에서 이만큼 앞이 스테이징
    docking_threshold_m: float = 0.05   # 접점이 맞물렸다고 볼 잔여 거리
    max_retries: int = 3                # 재시도 상한 — 도킹은 한 번에 되지 않는다
    undock_distance_m: float = 0.35     # 언도킹 후진 거리 (오도메트리 전용)
    # DNC-007 도크 태그 제원. 셋 중 하나라도 없으면 태그 검출기를 고를 수 없다 —
    # 크기를 모르면 상대 포즈를 풀 수 없으므로 fail-closed.
    tag_family: str = "DICT_4X4_50"
    tag_id: Optional[int] = None
    tag_size_m: Optional[float] = None
    # 주차형 도크 (차선망 미션 3단계, docs/plans/2026-09-23-lane-network-parking-design.md).
    # 기본값은 원래 도크의 동작 그대로다 — 이 필드들을 바꾼 기종만 달라진다.
    staging: bool = True                # False: Nav2 스테이징 없이 진입 회전부터
    approach: Literal["bearing", "pose"] = "bearing"   # pose: 도크 좌표계 정렬 접근
    settle: Literal["agent", "pose"] = "agent"         # pose: 접점 없이 포즈로 정착
    tag_offset_m: Optional[float] = None  # 주차점 → 태그 중심, 도크 축 방향 (pose 접근)
    acquire_creep_m: float = 0.0        # 태그가 안 보일 때 주차점 쪽으로 기어갈 거리
    backoff_m: Optional[float] = None   # 재시도 후진 거리 (오도메트리). None: 시간 기준
    undock_turn_rad: float = 0.0        # 언도킹 후진 뒤 목표 방위 = 도크 yaw + 이 값
    pose_tolerance_m: float = 0.012     # pose 정착 판정 (위치, 축 방향·횡 각각)
    pose_tolerance_rad: float = 0.0524  # pose 정착 판정 (방위, 3 deg)

    @field_validator("staging_offset_m")
    @classmethod
    def _staging_must_be_in_front(cls, value: float) -> float:
        # 스테이징은 도크 *앞* 이다. 0이나 음수는 도크 안이나 뒤를 가리킨다.
        if value <= 0.0:
            raise ValueError("staging_offset_m must be positive")
        return value

    @model_validator(mode="after")
    def _tag_spec_is_all_or_nothing(self) -> "DockType":
        if self.tag_id is not None and self.tag_id < 0:
            raise ValueError("tag_id must be non-negative")
        if self.tag_size_m is not None and self.tag_size_m <= 0.0:
            raise ValueError("tag_size_m must be positive")
        return self

    @model_validator(mode="after")
    def _parking_is_consistent(self) -> "DockType":
        # 포즈 접근은 주차점이 태그에서 얼마나 떨어졌는지 모르면 설 자리를 모른다.
        if self.approach == "pose" and not (self.tag_offset_m or 0.0) > 0.0:
            raise ValueError("a pose approach needs a positive tag_offset_m")
        # 포즈 정착은 포즈 접근이 세운 도크 좌표계로만 판정할 수 있다.
        if self.settle == "pose" and self.approach != "pose":
            raise ValueError("a pose settle needs a pose approach")
        if self.acquire_creep_m < 0.0 or (self.backoff_m is not None and self.backoff_m <= 0.0):
            raise ValueError("creep and backoff distances must be positive")
        if self.pose_tolerance_m <= 0.0 or self.pose_tolerance_rad <= 0.0:
            raise ValueError("pose tolerances must be positive")
        return self


class DockInstance(BaseModel):
    """도크 개체. 포즈는 맵 좌표계이며 teach-by-docking 으로 기록된다."""

    id: str
    type: str
    x: float = 0.0
    y: float = 0.0
    yaw: float = 0.0
    map_id: Optional[str] = None
    agent_url: Optional[str] = None     # 상태를 물어볼 도크 에이전트 주소
    metadata: dict = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _id_required(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("dock id required")
        return value

    def staging_pose(self, offset_m: float) -> Pose2D:
        """도크 정면 `offset_m` 앞의 포즈.

        저장하지 않고 매번 계산한다. 저장하면 teach 로 도크 포즈를 갱신했을 때
        낡은 스테이징 포즈가 남는다.
        """
        return Pose2D(
            x=self.x - offset_m * math.cos(self.yaw),
            y=self.y - offset_m * math.sin(self.yaw),
            yaw=self.yaw,               # 스테이징에서 도크를 마주 본다
        )

    def taught_at(self, x: float, y: float, yaw: float,
                  map_id: Optional[str]) -> "DockInstance":
        return self.model_copy(update={
            "x": float(x), "y": float(y), "yaw": float(yaw), "map_id": map_id,
        })

    def require_map(self, current_map: Optional[str]) -> None:
        """MAP-002 — 다른 맵의 도크로 가지 않는다.

        어느 한쪽이 맵을 모르면 검사하지 않는다. 맵 없이 운용하는 구성을
        막지 않기 위해서다 (resolve_goal 의 waypoint 검사와 같은 규칙).
        """
        if self.map_id and current_map and self.map_id != current_map:
            raise DockError(
                "MAP_MISMATCH",
                f"dock map '{self.map_id}' != current '{current_map}'")


class DockDatabase:
    """기종과 개체의 JSON 저장소."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = Path(path) if path is not None else None
        self._types: dict[str, DockType] = {}
        self._docks: dict[str, DockInstance] = {}
        self._load()

    @classmethod
    def empty(cls) -> "DockDatabase":
        """파일 없이 메모리에만 사는 저장소 — 테스트와 도크 미배치 구성."""
        return cls(None)

    # --- 영속 -----------------------------------------------------------------

    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        for item in raw.get("dock_types", []):
            dock_type = DockType.model_validate(item)
            self._types[dock_type.name] = dock_type
        for item in raw.get("docks", []):
            dock = DockInstance.model_validate(item)
            self._docks[dock.id] = dock

    def _save(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "dock_types": [t.model_dump() for t in self._types.values()],
            "docks": [d.model_dump() for d in self._docks.values()],
        }
        self._path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    # --- 기종 -----------------------------------------------------------------

    def add_type(self, dock_type: DockType) -> DockType:
        self._types[dock_type.name] = dock_type
        self._save()
        return dock_type

    def types(self) -> list[DockType]:
        return list(self._types.values())

    def type_of(self, dock_id: str) -> DockType:
        dock = self.get(dock_id)
        dock_type = self._types.get(dock.type)
        if dock_type is None:
            raise DockError("UNKNOWN_DOCK_TYPE",
                            f"dock type '{dock.type}' is not registered")
        return dock_type

    # --- 개체 -----------------------------------------------------------------

    def add(self, dock: DockInstance) -> DockInstance:
        if dock.id in self._docks:
            raise DockError("DOCK_EXISTS", f"dock '{dock.id}' already exists")
        if dock.type not in self._types:
            # 기종을 모르면 어떤 검출기를 쓸지 고를 수 없다.
            raise DockError("UNKNOWN_DOCK_TYPE",
                            f"dock type '{dock.type}' is not registered")
        self._docks[dock.id] = dock
        self._save()
        return dock

    def get(self, dock_id: str) -> DockInstance:
        dock = self._docks.get(dock_id)
        if dock is None:
            raise DockError("NOT_FOUND", f"dock '{dock_id}' not found")
        return dock

    def list(self) -> list[DockInstance]:
        return list(self._docks.values())

    def remove(self, dock_id: str) -> None:
        self.get(dock_id)
        del self._docks[dock_id]
        self._save()

    def teach(self, dock_id: str, x: float, y: float, yaw: float,
              map_id: Optional[str]) -> DockInstance:
        """teach-by-docking — 지금 로봇이 선 자리를 도크 포즈로 기록한다.

        줄자로 SLAM 맵 좌표를 재서 쓸 만한 값이 나오지 않는다. 그리고 이렇게
        기록하면 포즈가 나중에 복귀에 쓸 바로 그 맵과 자기모순 없이 일치한다.
        """
        taught = self.get(dock_id).taught_at(x=x, y=y, yaw=yaw, map_id=map_id)
        self._docks[dock_id] = taught
        self._save()
        return taught

    def only(self) -> Optional[DockInstance]:
        """도크가 정확히 하나면 그것 — 1:1 배치에서 이름 없이 "그 도크"를 묻는 길.

        0개거나 2개 이상이면 None 이다. 골라주는 것은 이 계층의 일이 아니다.
        """
        if len(self._docks) != 1:
            return None
        return next(iter(self._docks.values()))
