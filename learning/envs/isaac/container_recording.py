"""Continuous native camera footage, bound to physical ticks and registered bytes."""
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

from mapped_stack_fixture import DT, ROOT
from stacking_report import read_regular


class ContainerRecording:
    def __init__(self, directory, world, camera, config, reference):
        sys.path.insert(0, str(ROOT/'tools/sim/isaac'))
        from native_recording import NativeRecorder
        self.world, self.camera, self.config = world, camera, config
        self.reference = reference
        self.last_tick = -1
        self.last_reference = -1.
        self.recorder = NativeRecorder(directory/config['file'], width=config['width'],
                                       height=config['height'], fps=config['fps'], max_bitrate_kbps=220)

    def write(self, tick, pose, *, final=False):
        if tick == self.last_tick or not final and tick % self.config['every_control_ticks']:
            return
        for _ in range(self.config['max_render_updates']):
            self.world.render()
            frame = self.reference()
            if (isinstance(frame, dict) and type(frame.get('referenceTimeDenominator')) is int
                    and type(frame.get('referenceTimeNumerator')) is int and frame['referenceTimeDenominator'] > 0):
                stamp = frame['referenceTimeNumerator']/frame['referenceTimeDenominator']
                if stamp > self.last_reference:
                    break
        else:
            raise ValueError('Native render-product receipt did not advance within the capture budget')
        if self.recorder.frames < 3:
            print('CONTAINER_FRAME_SAMPLE', tick, frame, 'world_s', self.world.current_time,
                  'pose', list(map(float, pose)), flush=True)
        self.recorder.write(self.camera.get_rgba(), render_frame=frame,
            render_time=frame['referenceTimeNumerator']/frame['referenceTimeDenominator'],
            sim_s=tick*DT, pose=list(map(float, pose)))
        self.last_tick = tick
        self.last_reference = stamp

    def close(self):
        self.recorder.close()

    def manifest(self):
        paths = [(self.recorder.path, 'mapped-video', 'video/mp4'),
                 (self.recorder.path.with_suffix('.frames.jsonl'), 'mapped-video-frames', 'application/octet-stream'),
                 (self.recorder.path.with_suffix('.encoder.log'), 'mapped-video-encoder', 'text/plain')]
        return dict(file=self.recorder.path.name, fps=self.config['fps'], frames=self.recorder.frames,
            last_tick=self.last_tick, artifacts=[dict(id=ident, name=path.name, bytes=path.stat().st_size,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(), media_type=media)
                for path, ident, media in paths])


def verify_video(directory, video, fixture):
    config = fixture['recording']
    if (not isinstance(video, dict) or video.get('file') != config['file']
            or video.get('fps') != config['fps'] or type(video.get('frames')) is not int
            or video['frames'] < 2 or type(video.get('last_tick')) is not int):
        raise ValueError('Continuous video evidence is missing')
    expected = [('mapped-video', 'mapped-video.mp4', 'video/mp4', 64*1024*1024),
        ('mapped-video-frames', 'mapped-video.frames.jsonl', 'application/octet-stream', 16*1024*1024),
        ('mapped-video-encoder', 'mapped-video.encoder.log', 'text/plain', 1024*1024)]
    artifacts = video.get('artifacts')
    if not isinstance(artifacts, list) or len(artifacts) != len(expected):
        raise ValueError('Video artifacts are incomplete')
    for item, (ident, name, media, limit) in zip(artifacts, expected):
        raw = read_regular(Path(directory)/name, limit=limit, allow_empty=ident == 'mapped-video-encoder')
        if (item != dict(id=ident, name=name, bytes=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(), media_type=media)):
            raise ValueError('Video artifact differs from its registered bytes')
    receipts = [json.loads(line) for line in read_regular(
        Path(directory)/'mapped-video.frames.jsonl', limit=16*1024*1024).splitlines()]
    if (not receipts or not all(isinstance(row, dict) for row in receipts)
            or len(receipts) != video['frames'] or receipts[-1].get('sim_s') != video['last_tick']*DT):
        raise ValueError('Video does not cover the physical execution')
    previous_stamp = -1
    for i, row in enumerate(receipts):
        try:
            frame = row['render_frame']
            numerator, denominator = frame['referenceTimeNumerator'], frame['referenceTimeDenominator']
            pose = row['pose']
            valid = (type(numerator) is int and type(denominator) is int and denominator > 0
                and len(pose) == 5 and all(type(v) in (int, float) and math.isfinite(v)
                    for v in (row['sim_s'], row['render_time'], *pose)))
            stamp = numerator/denominator if valid else -1
        except (KeyError, TypeError, ZeroDivisionError, OverflowError):
            valid = False
            stamp = -1
        if not valid or i and stamp <= previous_stamp:
            raise ValueError('Native renderer receipt is invalid or stale')
        previous_stamp = stamp
        expected_time = min(i/config['fps'], video['last_tick']*DT)
        if (row.get('video_frame') != i or abs(row['sim_s']-expected_time) > 1e-7
                or i and (row['render_time'] <= receipts[i-1]['render_time']
                    or row['sim_s'] <= receipts[i-1]['sim_s'])):
            raise ValueError('Video frame timestamps are discontinuous')
    probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=codec_name,width,height,avg_frame_rate,nb_frames',
        '-of', 'json', str(Path(directory)/config['file'])], capture_output=True, check=True, timeout=60)
    streams = json.loads(probe.stdout)['streams']
    if (len(streams) != 1 or streams[0].get('codec_name') != 'h264'
            or streams[0].get('width') != config['width'] or streams[0].get('height') != config['height']
            or streams[0].get('avg_frame_rate') != str(config['fps'])+'/1'
            or int(streams[0].get('nb_frames', 0)) != video['frames']):
        raise ValueError('Decoded video stream differs from native frame evidence')
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-threads', '1', '-i', str(Path(directory)/config['file']),
        '-map', '0:v:0', '-f', 'null', '-'], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        check=True, timeout=120)
    return video
