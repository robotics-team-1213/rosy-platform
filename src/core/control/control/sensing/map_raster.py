"""Occupancy-grid rendering without ROS, shared by the web node and tests."""
import numpy as np

# concept 16 §6 — 서버가 굽는 /map.png와 브라우저 캔버스가 같은 색을 써야
# 오버레이가 섞인다. 계약 상대는 `src/control/web/dashboard.html`의
# --unk / --free / --wall 이며, `test_map_raster_color_contract.py`가 지킨다.
#
# 계약은 RGB로 적는다. cv2.imencode는 3채널 배열을 BGR로 읽으므로 변환은
# 아래에서 한 번만 한다. 예전에는 RGB 튜플을 BGR 배열에 그대로 넣어 PNG의
# 벽 색이 #e1e0d9(따뜻함)가 아니라 #d9e0e1(차가움)로 나왔다 — 지도에서
# 면적이 가장 큰 색이 뒤집혀 있었다. 이 구조는 그 실수를 다시 못 하게 한다.
OCCUPANCY_RGB = {
    'unknown': (0x16, 0x16, 0x15),
    'free': (0x23, 0x23, 0x22),
    'wall': (0xE1, 0xE0, 0xD9),
}

OCCUPANCY_BGR = {
    name: tuple(reversed(rgb)) for name, rgb in OCCUPANCY_RGB.items()
}

# ROS occupancy: -1 unknown, 0..100 occupied probability.
WALL_THRESHOLD = 65


def occupancy_bgr(data, width, height):
    """Return a top-down BGR image; ROS occupancy rows run south to north."""
    cells = np.asarray(data, dtype=np.int16).reshape(height, width)
    image = np.full((height, width, 3), OCCUPANCY_BGR['unknown'], dtype=np.uint8)
    image[(cells >= 0) & (cells < WALL_THRESHOLD)] = OCCUPANCY_BGR['free']
    image[cells >= WALL_THRESHOLD] = OCCUPANCY_BGR['wall']
    return np.ascontiguousarray(image[::-1])
