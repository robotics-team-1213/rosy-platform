"""web_node rasters: OccupancyGrid -> /map.png, camera frame -> /camera.jpg.

ROS-free: both functions read only message attributes, so host tests can drive
them with plain objects. numpy/opencv load lazily; without them the endpoint
is disabled with one printed warning instead of crashing the node.
"""
import time

from control.web_state import (
    CAM_JPG, CAM_MIN_DT, CAM_QUALITY, CAM_WIDTH, K_CAM, K_MAP, LOCK, MAP_PNG, STATE)


def render_png(msg, epoch=None):
    """OccupancyGrid -> PNG for /map.png.

    Colours live in `sensing.map_raster.OCCUPANCY_RGB` and are checked against
    the console canvas by `test_map_raster_color_contract.py`. Restating them
    here is what let the two drift apart, so this docstring names the source
    instead of repeating the values. Dark unknown recedes, light walls read as
    structure, and the overlays blend because both sides agree.
    """
    try:
        from control.sensing.map_raster import occupancy_bgr
        import cv2
    except ImportError:
        if not MAP_PNG.get('warned'):
            MAP_PNG['warned'] = True
            print('web_node: numpy/opencv missing — /map.png disabled '
                  '(install python3-numpy python3-opencv)')
        return
    info = msg.info
    img = occupancy_bgr(msg.data, info.width, info.height)
    ok, buf = cv2.imencode('.png', img)
    if ok:
        with LOCK:
            if epoch is not None and epoch != STATE.get('map_control', {}).get('epoch', 0):
                return
            MAP_PNG['bytes'] = buf.tobytes()
            MAP_PNG['gen'] += 1
            # Publish geometry and pixels together: SLAM can grow either edge.
            STATE[K_MAP] = [info.width, info.height, info.resolution,
                            info.origin.position.x, info.origin.position.y,
                            MAP_PNG['gen']]


def render_cam(msg):
    """/camera/front -> downscaled JPEG for /camera.jpg, throttled so a slow
    encode never backpressures the executor. BGR8 like camera_detect_node
    publishes (libcamera RGB888 is BGR in memory); rgb8 gets swapped."""
    try:
        import numpy as np
        import cv2
    except ImportError:
        if not CAM_JPG.get('warned'):
            CAM_JPG['warned'] = True
            print('web_node: numpy/opencv missing — /camera.jpg disabled')
        return
    now = time.monotonic()
    if now - CAM_JPG['t'] < CAM_MIN_DT:
        return
    h, w = msg.height, msg.width
    step = max(1, msg.step)
    if h <= 0 or w <= 0 or len(msg.data) < h * step:
        return
    img = np.frombuffer(bytes(msg.data[:h * step]), np.uint8)
    img = img.reshape(h, step)[:, :w * 3].reshape(h, w, 3)
    if msg.encoding == 'rgb8':
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    if w > CAM_WIDTH:
        img = cv2.resize(img, (CAM_WIDTH, max(1, int(h * CAM_WIDTH / w))))
    ok, buf = cv2.imencode('.jpg', img,
                           [int(cv2.IMWRITE_JPEG_QUALITY), CAM_QUALITY])
    if ok:
        with LOCK:
            CAM_JPG['bytes'] = buf.tobytes()
            CAM_JPG['gen'] += 1
            CAM_JPG['t'] = now
            STATE[K_CAM] = CAM_JPG['gen']
