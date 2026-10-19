"""Ideal SIM camera images; plant truth never enters observation payloads."""
import math

import cv2
import numpy as np

from rosy_vision.detect import generate_marker_image


class PipelineImages:
    def __init__(self, world, scene):
        self.world, self.scene = world, scene
        self.marker = generate_marker_image(7, 100)
        self.station_marker = generate_marker_image(33, 100)
        self.global_anchors = tuple(dict(marker_id=40+i,
            corners=((x, y), (x+49, y), (x+49, y+49), (x, y+49)))
            for i, (x, y) in enumerate(((5, 5), (545, 5), (545, 545), (5, 545))))

    def render_global(self):
        # Independent fixed camera/map; station carries this marker and its local docking camera.
        canvas = np.full((600, 600), 255, dtype=np.uint8)
        for anchor in self.global_anchors:
            x, y = anchor['corners'][0]
            canvas[y:y+50, x:x+50] = generate_marker_image(anchor['marker_id'], 50)
        centre = round((self.scene.station_x-.8)*1000)
        canvas[250:350, centre-50:centre+50] = self.station_marker
        ok, data = cv2.imencode('.jpg', canvas)
        assert ok
        return data.tobytes()

    def render(self, visible=True):
        canvas = np.full((600, 600), 255, dtype=np.uint8)
        if visible:
            x, y, yaw = self.world.pose
            cx, cy = round(300+(x-self.scene.station_x)*1000), round(300-y*1000)
            if 50 <= cx <= 550 and 50 <= cy <= 550:
                canvas[cy-50:cy+50, cx-50:cx+50] = self.marker
                canvas = cv2.warpAffine(canvas, cv2.getRotationMatrix2D((cx, cy), math.degrees(yaw), 1.),
                                        (600, 600), borderValue=255)
        ok, encoded = cv2.imencode('.jpg', canvas)
        assert ok
        return encoded.tobytes()
