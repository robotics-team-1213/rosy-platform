"""Synthetic camera renders of the parking wedge marker (test helper).

Ray-casts every pixel of the declared Gazebo camera (320x180, hfov 1.1519,
pitch 25 deg, optical centre 0.0602 m high and 0.0285 m ahead of base_link,
where the URDF and gz sdf put front_camera_link) against the floor and the inclined tag face, 4x4
supersampled so tag corners land with sub-pixel edges as a rendered image
has them. The floor carries lane_sim's paint raster (the 260919 STL paint)
or none; the wedge is the stage-3 marker (DICT_4X4_50 id 7, a 50 mm tag
with a one-cell white quiet zone, the face inclined FACE_TILT_RAD from the
floor, its bottom edge at BOTTOM_X facing -x). World frame: ROS map, x
right, y up; the robot pose is base_link (x, y, yaw).

Pixel centres follow Gazebo's renderer: pixel i's ray passes through
i + 0.5 from the image edge, so in OpenCV's convention (pixel centres on
integers) the principal point is ((W - 1) / 2, (H - 1) / 2), half a pixel
off the W / 2 that gz's camera_info reports (measured on the rendered
wedge: -0.5 px in u and v at three ranges).

Grey levels: floor and paint as lane_sim (109; 229 - 35 d); the tag's
white is WHITE, under line_observer's bright threshold 180 on purpose (the
design keeps the marker out of the paint pipeline), its black BLACK.
"""

import math

import cv2
import numpy as np

import lane_sim

FACE_TILT_RAD = math.radians(25.0)
TAG_SIZE_M = 0.050
QUIET_CELLS = 1
CELL_M = TAG_SIZE_M / 6.0
FACE_M = TAG_SIZE_M + 2 * QUIET_CELLS * CELL_M
BOTTOM_X = -0.78
TAG_ID = 7
WHITE, BLACK = 150, 20
SPOT = (-1.0, 0.0, 0.0)
ENTRY = (-1.2696, 0.0, 0.0)

HEIGHT_M = 0.060194
PITCH_RAD = math.radians(25.0)
CAM_X = 0.028481
W, H = 320, 180
HFOV = 1.1519
FOCAL = (W / 2.0) / math.tan(HFOV / 2.0)
CX, CY = (W - 1) / 2.0, (H - 1) / 2.0
CAMERA_MATRIX = np.array([[FOCAL, 0.0, CX], [0.0, FOCAL, CY], [0.0, 0.0, 1.0]])
DIST = np.zeros(5)
SUPERSAMPLE = 4


def marker_image(tag_id, side_px):
    """DICT_4X4_50 marker image: generateImageMarker on OpenCV >= 4.7,
    drawMarker before it (the ROS box's apt 4.6)."""
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    draw = getattr(cv2.aruco, "generateImageMarker", None) or cv2.aruco.drawMarker
    return draw(dictionary, tag_id, side_px)


def tag_texture(px_per_cell=40, tag_id=TAG_ID):
    """The face texture: the marker plus its white quiet zone, row 0 at the
    top of the slope, column 0 at the tag's left (+y seen from the bay)."""
    marker = marker_image(tag_id, 6 * px_per_cell)
    pad = QUIET_CELLS * px_per_cell
    return cv2.copyMakeBorder(marker, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)


def tag_centre(bottom_x=BOTTOM_X, tilt=FACE_TILT_RAD):
    """World (x, y, z) of the tag's centre on the face."""
    half = FACE_M / 2.0
    return (bottom_x + half * math.cos(tilt), 0.0, half * math.sin(tilt))


def _rays():
    """Camera-frame unit-less ray directions for the supersampled grid,
    shape (H, W, S*S, 3): x right, y down, z forward (OpenCV)."""
    offsets = (np.arange(SUPERSAMPLE) + 0.5) / SUPERSAMPLE - 0.5
    u = np.arange(W)[None, :, None, None] + offsets[None, None, None, :]
    v = np.arange(H)[:, None, None, None] + offsets[None, None, :, None]
    u, v = np.broadcast_arrays(u, v)
    x = (u - CX) / FOCAL
    y = (v - CY) / FOCAL
    return np.stack([x, y, np.ones_like(x)], axis=-1).reshape(H, W, -1, 3)


_RAYS = _rays()


def _mount_matrix(pitch=PITCH_RAD):
    """Columns: the camera's right, down, forward axes in base_link."""
    s, c = math.sin(pitch), math.cos(pitch)
    return np.array([[0.0, -s, c], [-1.0, 0.0, 0.0], [0.0, -c, -s]])


def render(pose, *, world=None, texture=None, bottom_x=BOTTOM_X, tilt=FACE_TILT_RAD,
           pitch=PITCH_RAD, height=HEIGHT_M, marker=True):
    """Grey frame (H, W) uint8 seen from base_link `pose` (x, y, yaw)."""
    texture = tag_texture() if texture is None else texture
    x, y, yaw = (float(v) for v in pose)
    c, s = math.cos(yaw), math.sin(yaw)
    to_world = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]]) @ _mount_matrix(pitch)
    d = _RAYS @ to_world.T                                   # world ray directions
    origin = np.array([x + CAM_X * c, y + CAM_X * s, height])

    shade = np.full(d.shape[:-1], float(lane_sim.FLOOR))
    t_floor = np.where(d[..., 2] < 0.0, -origin[2] / np.minimum(d[..., 2], -1e-12), np.inf)
    hit = origin + d * t_floor[..., None]
    if world is not None:
        col = np.rint((hit[..., 0] - world.x0) * 1000).astype(np.int64)
        row = np.rint((world.y1 - hit[..., 1]) * 1000).astype(np.int64)
        inside = (np.isfinite(t_floor) & (col >= 0) & (row >= 0)
                  & (col < world.paint.shape[1]) & (row < world.paint.shape[0]))
        painted = np.zeros(shade.shape, bool)
        painted[inside] = world.paint[row[inside], col[inside]] > 0
        forward = np.hypot(hit[..., 0] - origin[0], hit[..., 1] - origin[1])
        shade[painted] = np.clip(229.0 - 35.0 * forward[painted], 0, 255)

    if marker:
        up = np.array([math.cos(tilt), 0.0, math.sin(tilt)])       # up the slope
        across = np.array([0.0, 1.0, 0.0])
        normal = np.cross(up, across)                              # (-sin, 0, cos)
        corner = np.array([bottom_x, -FACE_M / 2.0, 0.0])
        denom = d @ normal
        with np.errstate(divide="ignore", invalid="ignore"):
            t_face = ((corner - origin) @ normal) / denom
        on = origin + d * t_face[..., None] - corner
        a, b = on @ across, on @ up                              # metres on the face
        face = (np.isfinite(t_face) & (t_face > 0) & (t_face < t_floor)
                & (a >= 0) & (a < FACE_M) & (b >= 0) & (b < FACE_M))
        n = texture.shape[0]
        tex_col = np.clip(((FACE_M - a[face]) / FACE_M * n).astype(int), 0, n - 1)
        tex_row = np.clip(((FACE_M - b[face]) / FACE_M * n).astype(int), 0, n - 1)
        shade[face] = np.where(texture[tex_row, tex_col] > 127, WHITE, BLACK)

    frame = np.rint(shade.mean(axis=-1)).astype(np.uint8)
    frame[139:, :] = lane_sim.BODY
    return frame


def truth(pose, bottom_x=BOTTOM_X, tilt=FACE_TILT_RAD):
    """The tag's centre (x, y) and inward-axis yaw in base_link at `pose`."""
    x, y, yaw = (float(v) for v in pose)
    cx, cy, _ = tag_centre(bottom_x, tilt)
    c, s = math.cos(yaw), math.sin(yaw)
    dx, dy = cx - x, cy - y
    return (c * dx + s * dy, -s * dx + c * dy, math.atan2(math.sin(-yaw), math.cos(-yaw)))
