"""Photometric screening of original frames; never a mechanical or task-success gate."""
import math

POLICY = 'omx-photometric-v3'


def advancing_frame(item, previous):
    stamp, seq = item.get('source_stamp'), item.get('sequence')
    quality = item.get('quality') or {}
    return (type(stamp) in (int, float) and math.isfinite(stamp)
            and type(seq) is int and stamp > previous[0] and seq > previous[1]
            and item.get('fresh') is True and quality.get('policy') == POLICY
            and type(quality.get('usable')) is bool
            and quality.get('condition') in {'NORMAL', 'UNDEREXPOSED', 'OVEREXPOSED',
                                           'MIXED_LIGHTING', 'LOW_CONTRAST', 'LOW_SPATIAL_SIGNAL'}
            and all(type(quality.get(key)) in (int, float) and math.isfinite(quality[key])
                    for key in ['mean_intensity', 'spatial_contrast', 'clipped_fraction']))


def frame_quality(pixels):
    import numpy as np
    if pixels.dtype != np.uint8 or pixels.ndim != 3 or pixels.shape[2] != 3:
        raise ValueError('quality requires original uint8 three-channel pixels')
    gray = pixels[::4, ::4].mean(axis=2)
    p5, p95 = (float(value) for value in np.percentile(gray, [5, 95]))
    mean = float(gray.mean())
    dark = float((gray < 15).mean())
    clipped = float((gray > 245).mean())
    tiles = [float(tile.mean()) for row in np.array_split(gray, 4, axis=0)
             for tile in np.array_split(row, 4, axis=1)]
    spatial_contrast = float(np.percentile(tiles, 95)-np.percentile(tiles, 5))
    if dark > .25 and clipped > .05:
        condition = 'MIXED_LIGHTING'
    elif clipped > .15:
        condition = 'OVEREXPOSED'
    elif mean < 25 or dark > .65:
        condition = 'UNDEREXPOSED'
    elif p95-p5 < 12:
        condition = 'LOW_CONTRAST'
    elif spatial_contrast < 12:
        condition = 'LOW_SPATIAL_SIGNAL'
    else:
        condition = 'NORMAL'
    return dict(policy=POLICY, mean_intensity=mean, p5=p5, p95=p95,
                dark_fraction=dark, clipped_fraction=clipped,
                spatial_contrast=spatial_contrast, condition=condition,
                usable=condition == 'NORMAL',
                scope='photometric_only_not_visibility_or_motion_acceptance')


class Readiness:
    """Both cameras must supply distinct, fresh, satisfactory original frames."""
    def __init__(self, required=3):
        if type(required) is not int or required < 1:
            raise ValueError('positive confirmation count required')
        self.required = required
        self.previous = {}
        self.counts = dict(top=0, front=0)

    def update(self, state):
        for role in self.counts:
            item = state.get(role, {})
            stamp, seq = item.get('source_stamp'), item.get('sequence')
            previous = self.previous.get(role, (0, 0))
            valid = advancing_frame(item, previous)
            quality = item.get('quality') or {}
            good = (valid and item.get('fresh') is True and quality.get('usable') is True
                    and quality.get('condition') == 'NORMAL' and quality.get('policy') == POLICY)
            self.counts[role] = self.counts[role]+1 if good else 0
            if valid:
                self.previous[role] = (stamp, seq)
        return dict(photometric_ready=all(n >= self.required for n in self.counts.values()),
                    confirmations=dict(self.counts), motion_admitted=False,
                    physical_acceptance=False, policy=POLICY)
