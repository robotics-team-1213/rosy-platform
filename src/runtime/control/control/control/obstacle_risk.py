"""Subject: short-horizon relative collision evidence; never motor authority."""
import math
import json
from dataclasses import dataclass

TRACK_UNCERTAINTY = .03


@dataclass(frozen=True)
class TrackedEvidence:
    tracks_json: str
    camera_json: str
    pose: tuple
    pose_observed_at: float
    radius: float
    margin: float

    @classmethod
    def capture(cls, tracks, camera, pose, pose_stamp, *, source_now, received_at, radius, margin):
        """Freeze packets and translate their common ROS clock to monotonic time.

        Capture beside sensor classification, not inside the CORE output loop.
        Pose must be in the same robot's odom frame as the track packet.
        """
        values = (*pose, pose_stamp, source_now, received_at, radius, margin)
        if (len(pose) != 3 or not all(type(v) in (int, float) and math.isfinite(v) for v in values) or
                radius <= 0 or margin < 0):
            raise ValueError('Invalid tracking geometry or clocks')
        def freeze(packet):
            stamp = packet['stamp']
            if type(stamp) not in (int, float) or not math.isfinite(stamp):
                raise ValueError('Invalid observation stamp')
            text = json.dumps(dict(packet, stamp=received_at - (source_now - stamp)), allow_nan=False)
            if len(text.encode('utf-8')) > 32768:
                raise ValueError('Tracking evidence exceeds size bound')
            return text
        if not isinstance(tracks.get('tracks'), list) or len(tracks['tracks']) > 64:
            raise ValueError('Tracking evidence requires at most 64 tracks')
        return cls(freeze(tracks), freeze(camera), tuple(pose),
                   received_at - (source_now - pose_stamp), radius, margin)

    def evaluate(self, speed, now):
        if (type(self.tracks_json) is not str or type(self.camera_json) is not str or
                len(self.tracks_json.encode('utf-8')) > 32768 or len(self.camera_json.encode('utf-8')) > 32768 or
                type(self.pose) is not tuple or len(self.pose) != 3 or
                not all(type(v) in (int, float) and math.isfinite(v)
                        for v in (*self.pose, self.pose_observed_at, self.radius, self.margin, speed, now)) or
                self.radius <= 0 or self.margin < 0):
            return dict(action='stop', reason='invalid_tracking_evidence')
        tracks, camera = json.loads(self.tracks_json), json.loads(self.camera_json)
        if not isinstance(tracks.get('tracks'), list) or len(tracks['tracks']) > 64:
            return dict(action='stop', reason='invalid_tracking_evidence')
        hold = camera_hold(camera, now)
        if hold:
            return dict(action='limit' if hold == 'camera_obstacle_unranged' else 'stop', reason=hold)
        if not 0 <= now - self.pose_observed_at <= .3:
            return dict(action='stop', reason='obstacle_pose_unavailable')
        result = observation_risk(tracks, now, self.pose, speed, self.radius, self.margin)
        if result['action'] == 'clear' or (result['action'] == 'replan' and speed == 0.):
            # The existing full rotation envelope still owns spin clearance.
            return dict(action='clear', reason='clear')
        if result['reason'] == 'predicted_obstacle':
            return dict(action='limit', reason='obstacle_' + result['action'])
        return dict(action='stop', reason=result['reason'])


def accept_observation(value, previous, now, max_age=.5):
    """Reject unusable source time before updating the monotonic watermark."""
    try:
        stamp = value['stamp']
        if (type(stamp) not in (int, float) or not math.isfinite(stamp) or
                not 0 <= now-stamp <= max_age or
                (previous is not None and stamp <= previous['stamp'])):
            return previous
        return value
    except (KeyError, TypeError, ValueError):
        return previous


def camera_hold(evidence, now, max_age=.5):
    try:
        if 'quality' in evidence and evidence['quality']['valid'] is not True:
            raise ValueError('Unusable image evidence')
        if not 0 <= now-evidence['stamp'] <= max_age or type(evidence['blocked']) is not bool:
            raise ValueError('Invalid image evidence')
        return 'camera_obstacle_unranged' if evidence['blocked'] else None
    except (TypeError, KeyError, ValueError):
        return 'camera_observation_unavailable'


def observation_risk(evidence, now, pose, speed, radius, margin, max_age=.3):
    try:
        age = now-evidence['stamp']
        if not 0 <= age <= max_age or evidence['frame'] != 'odom':
            raise ValueError('Stale or incompatible observation')
        tracks = [dict(t, age=t['age']+age) for t in evidence['tracks']]
    except (TypeError, KeyError, ValueError):
        return dict(action='wait', reason='obstacle_observation_unavailable', ids=[])
    return collision_risk(tracks, pose, speed, radius, margin)


def collision_risk(tracks, pose, speed, radius, margin, horizon=2., uncertainty=TRACK_UNCERTAINTY):
    values = (*pose, speed, radius, margin, horizon, uncertainty)
    if not all(math.isfinite(v) for v in values) or radius <= 0 or min(margin, uncertainty) < 0 or horizon <= 0:
        return dict(action='wait', reason='invalid_geometry', ids=[])
    vx, vy = speed*math.cos(pose[2]), speed*math.sin(pose[2])
    action, ids = 'clear', []
    for t in tracks:
        try:
            px, py = t['position'][0]-pose[0], t['position'][1]-pose[1]
            ox, oy = t['velocity']
            extent = float(t.get('radius', 0.))
            age = float(t['age'])
            if not all(math.isfinite(v) for v in (px, py, ox, oy, extent, age)) or min(extent, age) < 0:
                raise ValueError('Invalid track')
            dx, dy = ox-vx, oy-vy
            norm = dx*dx+dy*dy
            closest = max(0., min(horizon, -(px*dx+py*dy)/norm)) if norm > 1e-12 else 0.
            envelope = radius+margin+extent+uncertainty+age*math.hypot(ox, oy)
            if math.hypot(px+dx*closest, py+dy*closest) > envelope:
                continue
            ids.append(t.get('id'))
            state = t['state'] if t.get('observed') else 'unknown'
            candidate = 'replan' if state == 'stationary' else 'wait'
            if action != 'wait':
                action = candidate
        except (KeyError, TypeError, ValueError, IndexError):
            return dict(action='wait', reason='invalid_track', ids=[])
    return dict(action=action, reason='predicted_obstacle' if ids else 'clear', ids=ids)
