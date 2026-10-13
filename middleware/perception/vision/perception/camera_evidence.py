"""Subject: what the camera can honestly claim, and how it says it on the wire.

One serialiser, so the real node and the Gazebo adapter cannot describe the same
observation differently -- they did, and the divergence was invisible because
nothing downstream reads the regions yet.

Wire schema for `regions` (short keys because this goes out at the frame rate):
  b  bbox as [x0, y0, x1, y1] in image pixels
  n  1 when the region reaches the near centre path, else 0
  k  'd' dark region, 'f' foreground region
  m  forward distance from the camera in metres; ABSENT means unranged, never zero
  s  which sensor measured m (D-423): 'L' LiDAR in the region's bearing span,
     'G' ground plane at the region's bottom edge. Only with m; a region from
     before D-423 has m without s, which reads as source not stated.

Optional top-level `ground_source` names the floor geometry (PINHOLE,
HOMOGRAPHY, NOMINAL); absent when the producer does not say.

Measured: the previous verbose form reached 11362 B at the 64-region cap, larger
than shipping the whole frame as JPEG (9813 B at q70), which defeated the point
of publishing evidence instead of pixels.
"""

# 48, not 64: the worst case must stay under 4 KB once regions carry a measured
# distance too. Measured at 320x240 with 3-digit boxes and a 3-decimal range --
# cap 64 ranged = 4135 B, cap 48 ranged = 3175 B. Regions arrive sorted by
# (near_path, area_px) so the cap drops the least significant, and region_count
# still reports the true total. Real frames produce 5 and 9 regions. D-423 adds
# 's' to every ranged region; the worst case stays under 4 KB (test_camera_policy).
REGION_CAP = 48


def legacy_flags(result, previous_cliff=False):
    """Conservative flags when a camera observation cannot be evaluated."""
    if not result.get('quality', {}).get('valid', False):
        # Blindness requires a hold, but is not evidence of a new cliff.
        return bool(previous_cliff), True
    return bool(result['cliff']), bool(result['blocked'])


def encode_region(region):
    """One region, compactly. Distance is omitted rather than faked."""
    encoded = {
        'b': [int(v) for v in region['bbox_xyxy']],
        'n': int(bool(region.get('near_path'))),
        'k': 'd' if region.get('kind') == 'dark_region' else 'f',
    }
    distance = region.get('distance_m')
    if distance is not None:
        encoded['m'] = round(float(distance), 3)
        if region.get('range_source') in ('L', 'G'):
            encoded['s'] = region['range_source']
    return encoded


def observation_payload(stamp, cliff, blocked, side, result, image_size, source,
                        detector='floor_foreground_v3', ground_source=None):
    """The evidence message. Verdicts come from the policy, facts from the frame.

    v3, not v2: the region schema is compact now, and `cliff` is constant False
    because the camera withdrew that verdict. The live capture in
    docs/validation/detector-main-8e9cb78/ was recorded against v2 and describes
    different behaviour, so the label has to separate them.
    """
    regions = result.get('regions', [])
    payload = {
        'stamp': float(stamp),
        'blocked': bool(blocked),
        'cliff': bool(cliff),
        'side': float(side),
        'source': source,
        'detector': detector,
        'quality': result['quality'],
        'regions': [encode_region(r) for r in regions[:REGION_CAP]],
        'region_count': int(result.get('region_count', len(regions))),
        'regions_truncated': bool(result.get('region_count', len(regions)) > REGION_CAP),
        'image_size': [int(image_size[0]), int(image_size[1])],
    }
    if ground_source is not None:
        payload['ground_source'] = str(ground_source)
    return payload
