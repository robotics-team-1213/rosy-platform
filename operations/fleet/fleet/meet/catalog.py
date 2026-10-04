"""알고리즘 이름표.

새 알고리즘은 `decide(scene) -> orders` 를 가진 객체로 `register` 하면 된다.
장면과 주문은 `scene` 에 있고, 이 모듈은 누구를 골랐는지만 확인한다.
고른 알고리즘이 로봇을 빠뜨리거나 두 번 주문하면 실행 전에 거절한다.
"""

from __future__ import annotations

from typing import Protocol

from fleet.meet.scene import Order, Scene


class MeetAlgorithm(Protocol):
    name: str

    def decide(self, scene: Scene) -> tuple[Order, ...]:
        """장면의 로봇마다 주문 하나."""


REGISTRY: dict[str, MeetAlgorithm] = {}


def register(algorithm: MeetAlgorithm) -> MeetAlgorithm:
    if algorithm.name in REGISTRY:
        raise ValueError(f"meet algorithm already registered: {algorithm.name}")
    REGISTRY[algorithm.name] = algorithm
    return algorithm


def names() -> tuple[str, ...]:
    return tuple(sorted(REGISTRY))


def decide(name: str, scene: Scene) -> tuple[Order, ...]:
    try:
        algorithm = REGISTRY[name]
    except KeyError:
        known = ", ".join(names()) or "(none)"
        raise KeyError(f"unknown meet algorithm {name!r}; known: {known}") from None
    orders = tuple(algorithm.decide(scene))
    got = [order.robot_id for order in orders]
    want = [robot.id for robot in scene.robots]
    if sorted(got) != sorted(want) or len(got) != len(set(got)):
        raise ValueError(
            f"{name} must order each robot once; got {got}, scene has {want}"
        )
    return orders
