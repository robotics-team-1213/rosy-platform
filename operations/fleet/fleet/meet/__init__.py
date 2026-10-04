"""한 줄에서 로봇이 만날 때의 알고리즘 자리.

장면을 만들고 `decide(이름, 장면)` 을 부른다. 이름을 바꾸면 같은 장면에서
다른 주문이 나온다. 알고리즘을 더하려면 `decide` 를 구현하고 `register` 한다.
콘솔과 차선 추종은 이 주문을 아직 실행하지 않는다.
"""

from fleet.meet.catalog import decide, names, register
from fleet.meet.room_hold import RoomHold
from fleet.meet.scene import Action, Door, Edge, Order, Pin, Robot, Room, Scene
from fleet.meet.wait_both import WaitBoth

# 알고리즘을 더하려면 클래스를 만들고 여기에 한 줄 등록한다.
register(RoomHold())
register(WaitBoth())

__all__ = [
    "Action", "Door", "Edge", "Order", "Pin", "Robot", "Room", "Scene",
    "decide", "names", "register",
]
