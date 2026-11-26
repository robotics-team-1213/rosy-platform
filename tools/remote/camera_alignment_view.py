"""Loopback live camera alignment viewer. Input profiles bind a view, reference JPEG and fixed pixel points."""
import argparse
import base64
import json
import math
import secrets
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import cv2
import numpy as np
import rosy_agent_bridge
import rosy_cli


def pairs(reference, current, points):
    """Project fixed landmarks, then verify each against its local reference patch."""
    if reference.shape != current.shape:
        return [None] * len(points)
    orb = cv2.ORB_create(3000)
    a, ad = orb.detectAndCompute(reference, None)
    b, bd = orb.detectAndCompute(current, None)
    missing = [None] * len(points)
    if ad is None or bd is None:
        return missing
    matches = sorted(cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(ad, bd),
                     key=lambda m: m.distance)[:600]
    if len(matches) < 30:
        return missing
    src = np.float32([a[m.queryIdx].pt for m in matches])
    dst = np.float32([b[m.trainIdx].pt for m in matches])
    matrix, mask = cv2.findHomography(src, dst, cv2.RANSAC, 3)
    if matrix is None or mask.sum() < 25:
        return missing
    h, w = reference.shape
    aligned = cv2.warpPerspective(current, matrix, (w, h), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
    found = []
    for x, y in points:
        r = 14
        template = reference[y-r:y+r+1, x-r:x+r+1]
        search = aligned[y-r-5:y+r+6, x-r-5:x+r+6]
        if template.shape != (29, 29) or search.shape != (39, 39) or template.std() < 8:
            found.append(None)
            continue
        _, score, _, (dx, dy) = cv2.minMaxLoc(cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED))
        px, py = cv2.perspectiveTransform(np.float32([[[x+dx-5, y+dy-5]]]), matrix)[0, 0]
        found.append([round(float(px),1), round(float(py),1)] if score >= .72 and 0 <= px < w and 0 <= py < h else None)
    return found


def load_profiles(path):
    profiles = json.loads(path.read_text(encoding="utf-8-sig"))
    for row in profiles:
        raw = (path.parent / row["reference"]).read_bytes()
        row["gray"] = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
        if row["gray"] is None:
            raise ValueError("Invalid reference JPEG")
        row["jpeg"] = base64.b64encode(raw).decode("ascii")
    return profiles


def frame(bridge, profile):
    res = bridge.call_tool("cell_frame", {"view": profile["view"]})
    if not res.get("ok"):
        raise ValueError("카메라 연결 대기")
    headers = res["frame_headers"]
    stamp = float(headers["X-Source-Stamp"])
    age = time.time() - stamp
    # Camera and viewer hosts have separate clocks. The UI also checks sequence progress.
    if not math.isfinite(age) or abs(age) > 10:
        raise ValueError("새 프레임 대기")
    img = cv2.imdecode(np.frombuffer(base64.b64decode(res["image_b64"]), np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None or img.shape != profile["gray"].shape:
        raise ValueError("기준 영상과 해상도 불일치")
    return dict(seq=int(headers["X-Frame-Seq"]), image=res["image_b64"], stamp=stamp,
                points=pairs(profile["gray"], img, profile["points"]))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("profiles", type=Path)
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args()
    profiles = load_profiles(args.profiles)
    cfg = rosy_cli.build_parser().parse_args(["--config", str(args.config), "--timeout-s", "2", "snapshot"])
    bridge = rosy_agent_bridge.RosyAgentBridge(rosy_agent_bridge.build_config(cfg))
    page = Path(__file__).with_suffix(".html").read_bytes()
    prefix = "/" + secrets.token_urlsafe(20) + "/"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            path = self.path.split("?")[0]
            if not path.startswith(prefix):
                self.send_error(404)
                return
            route = path[len(prefix):]
            kind = "application/json"
            if not route:
                kind, body = "text/html; charset=utf-8", page
            elif route == "profiles":
                body = json.dumps([{k: r[k] for k in ("name","points","jpeg")} for r in profiles]).encode()
            elif route.startswith("frame/") and route[6:] in {str(i) for i in range(len(profiles))}:
                try:
                    result = frame(bridge, profiles[int(route[6:])])
                except (ValueError, KeyError, TypeError, OSError, cv2.error):
                    result = {"error":"새 영상 또는 추적 가능한 프레임 대기"}
                body = json.dumps(result).encode()
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (ConnectionError, OSError):
                pass

    with HTTPServer(("127.0.0.1", args.port), Handler) as server:
        print(f"http://127.0.0.1:{server.server_port}{prefix}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()

