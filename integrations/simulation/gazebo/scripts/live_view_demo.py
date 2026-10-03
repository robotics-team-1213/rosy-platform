"""`lane_live_view.py --demo`: a canned mission fed through the viewer's
own state setters (no ROS, no CORE), so the page can be checked and shown
without Gazebo. One cycle walks every phase: boot, dock confirm, undock,
the all-lane tour, park, done; then a new run starts.

It only writes into the viewer's in-process ViewerState; like the viewer
it publishes nothing and calls no API."""

import math
import time

import cv2
import numpy as np

#: Phase durations (demo seconds); the tour's comes from its length.
BOOT_S, CONFIRM_S, UNDOCK_S, PARK_S, DONE_S = 3.0, 4.0, 4.0, 6.0, 6.0
TOUR_SPEED_M_S = 0.6
SIM_RTF = 0.46
FRAME_HZ = 5.0
STEP_S = 0.05


class DemoSource:
    def __init__(self, state, make_frames=True):
        self.state = state
        self.make_frames = make_frames
        self.route = state.route
        self.spot = state.spot or (-1.0, 0.0, 0.0)
        self.junction = self.route.point_at(0.0)
        self.tour_s = self.route.length_m / TOUR_SPEED_M_S
        marks = [BOOT_S, CONFIRM_S, UNDOCK_S, self.tour_s, PARK_S, DONE_S]
        self.bounds = np.cumsum(marks)
        self.cycle_s = float(self.bounds[-1])
        self._last_frame = -1.0
        self._cycle = -1

    # -- the canned run --------------------------------------------------

    def _pose(self, phase, u):
        """(x, y, yaw) for `phase` at fraction u of it."""
        sx, sy, syaw = self.spot
        jx, jy, jheading = self.junction
        if phase in ("boot", "confirm", "done"):
            return sx, sy, syaw
        if phase == "undock":  # back out along the spur, then turn onto the road
            k = min(u / 0.7, 1.0)
            yaw = syaw if u < 0.7 else syaw + (jheading - syaw) * (u - 0.7) / 0.3
            return sx + (jx - sx) * k, sy + (jy - sy) * k, yaw
        if phase == "tour":
            return self.route.point_at(u * self.route.length_m)
        k = max(0.0, (u - 0.25) / 0.75)  # park: turn in, then creep to the spot
        return jx + (sx - jx) * k, jy + (sy - jy) * k, syaw if u > 0.25 else jheading

    def _confidence(self, t):
        wobble = 0.5 + 0.5 * math.sin(t * 0.9) * math.sin(t * 0.37 + 1.0)
        if wobble > 0.82:
            return 0.6    # MEMORY
        if wobble > 0.62:
            return 0.78   # ONE
        return 0.9 + 0.05 * math.sin(t * 3.0)  # BOTH

    def step(self, t, now=None):
        now = t if now is None else now
        s = self.state
        cycle, tc = divmod(t, self.cycle_s)
        if cycle != self._cycle:
            self._cycle = cycle
            s.new_run()
        i = int(np.searchsorted(self.bounds, tc, side="right"))
        phase = ("boot", "confirm", "undock", "tour", "park", "done")[min(i, 5)]
        start = 0.0 if i == 0 else float(self.bounds[i - 1])
        u = (tc - start) / (float(self.bounds[min(i, 5)]) - start)

        docking = {"boot": "UNDOCKED", "confirm": "DOCKING" if u < 0.5 else "DOCKED",
                   "undock": "UNDOCKING", "tour": "UNDOCKED",
                   "park": "DOCKING", "done": "DOCKED"}[phase]
        dock_phase = {"confirm": "settling", "park": "approach" if u < 0.7 else "align"}.get(phase)
        touring = phase == "tour"
        error = 0.012 * math.sin(t * 1.3) if touring else None
        conf = self._confidence(t) if touring else 0.0
        line = {"mode": "CAMERA_LINE" if touring else "OFF",
                "state": "FOLLOWING" if touring else "OFF",
                "source": "camera" if touring else None, "error": error,
                "confidence": conf, "age_s": 0.05 if touring else None,
                "linear": round(0.08 * conf, 3) if touring else 0.0,
                "angular": round(-4.0 * (error or 0.0), 3),
                "reason": "ok" if touring else "mode_off"}
        x, y, yaw = self._pose(phase, u)
        s.on_clock(tc * SIM_RTF, now)
        if phase != "boot":
            s.set_core_status({"ok": True, "line_follow": line,
                               "robot": {"mode": "NAVIGATION" if touring else
                                         "DOCKING" if docking in ("DOCKING", "UNDOCKING")
                                         else "IDLE",
                                         "safety": {"estop": False},
                                         "velocity": {"linear": line["linear"],
                                                      "angular": line["angular"]}},
                               "docking": {"state": docking, "dock_id": "parking",
                                           "phase": dock_phase, "retries": 0, "error": None,
                                           "supported": True}}, now)
        else:
            s.set_core_status({"ok": False}, now)
        s.add_pose(x, y, yaw, now, speed=line["linear"])
        s.set_observation({"source": "camera", "stamp": tc, "visible": touring,
                           "error": error, "confidence": conf}, now)
        range_m = math.hypot(-0.78 - x, -y)
        if phase in ("confirm", "park", "done") and range_m < 0.5:
            s.set_dock_observation({"source": "CAMERA_TAG", "stamp": tc, "visible": True,
                                    "tag_id": 0, "x": round(range_m, 4),
                                    "y": round(-y, 4), "yaw": round(-(yaw - self.spot[2]), 4),
                                    "range_m": round(range_m, 4), "confidence": 0.93}, now)
        s.tick(now)
        if self.make_frames and now - self._last_frame >= 1.0 / FRAME_HZ:
            self._last_frame = now
            s.camera.publish(_jpeg(_camera_frame(t, error or 0.0)), now)
            if touring:
                s.overlay.publish(_jpeg(_overlay_frame(t, error or 0.0, conf)), now)

    def run(self, stop_event):
        t0 = time.monotonic()
        while not stop_event.is_set():
            now = time.monotonic()
            self.step(now - t0, now)
            stop_event.wait(STEP_S)


# -- synthetic frames ------------------------------------------------------


def _jpeg(image):
    return cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()


def _camera_frame(t, error, w=640, h=480):
    img = np.zeros((h, w, 3), np.uint8)
    img[:] = (58, 60, 62)
    img[: h // 3] = (92, 88, 84)
    shift = int(error * 4000)
    for side in (-1, 1):
        top = (w // 2 + side * 60 + shift // 3, h // 3)
        bottom = (w // 2 + side * 290 + shift, h)
        cv2.line(img, top, bottom, (235, 235, 235), 9, cv2.LINE_AA)
    cv2.putText(img, "DEMO camera/front", (14, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                (200, 200, 200), 2, cv2.LINE_AA)
    return img


def _overlay_frame(t, error, conf, w=640, h=480):
    """Four panels like line/debug/compressed: green = left line, blue =
    right line, yellow = route, the dark bottom band = robot body."""
    pw, ph = w // 2, h // 2
    img = np.zeros((h, w, 3), np.uint8)
    shift = int(error * 3000)
    titles = ("camera", "bird's-eye", "lines", "route")
    for k, title in enumerate(titles):
        ox, oy = (k % 2) * pw, (k // 2) * ph
        panel = img[oy:oy + ph, ox:ox + pw]
        panel[:] = (34, 36, 40) if k else (60, 62, 64)
        cx = pw // 2 + shift
        cv2.line(panel, (cx - 70, 20), (cx - 90, ph - 30), (80, 220, 80), 4, cv2.LINE_AA)
        if conf >= 0.85 or k == 0:
            cv2.line(panel, (cx + 70, 20), (cx + 90, ph - 30), (255, 140, 40), 4, cv2.LINE_AA)
        if k == 3:
            cv2.line(panel, (pw // 2, ph - 30), (cx, 20), (40, 210, 240), 3, cv2.LINE_AA)
        panel[ph - 26:] = (18, 18, 20)
        cv2.putText(panel, title, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (220, 220, 220), 1,
                    cv2.LINE_AA)
    cv2.line(img, (pw, 0), (pw, h), (90, 90, 90), 1)
    cv2.line(img, (0, ph), (w, ph), (90, 90, 90), 1)
    return img
