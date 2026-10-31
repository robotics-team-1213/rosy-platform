"""Encode actual Isaac camera frames with physics and renderer timestamps."""
import json
import math
import subprocess


class NativeRecorder:
    def __init__(self, path, *, width=960, height=540, fps=25, max_bitrate_kbps=None):
        if type(fps) is not int or not 1 <= fps <= 60:
            raise ValueError('fps must be an integer from 1 to 60')
        if max_bitrate_kbps is not None and (type(max_bitrate_kbps) is not int or max_bitrate_kbps <= 0):
            raise ValueError('maximum bitrate must be a positive integer in kbps')
        rate_limit = ([] if max_bitrate_kbps is None else
                      ['-maxrate', f'{max_bitrate_kbps}k', '-bufsize', f'{max_bitrate_kbps}k'])
        self.path = path
        self.width, self.height = width, height
        self.frames = 0
        self.previous = (-1, -1., -1.)
        self.closed = False
        self.receipts = path.with_suffix('.frames.jsonl').open('x')
        self.errors = path.with_suffix('.encoder.log').open('xb')
        try:
            self.process = subprocess.Popen([
                'ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-n',
                '-f', 'rawvideo', '-pixel_format', 'rgb24', '-video_size', f'{width}x{height}',
                '-framerate', str(fps), '-i', 'pipe:0', '-an', '-c:v', 'libx264',
                '-preset', 'ultrafast', '-threads', '1', '-crf', '20', *rate_limit, '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart', str(path)], stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL, stderr=self.errors)
        except Exception:
            self.receipts.close()
            self.errors.close()
            raise

    def write(self, rgba, *, render_frame, render_time, sim_s, pose):
        if self.closed or rgba.shape != (self.height, self.width, 4) or str(rgba.dtype) != 'uint8':
            raise ValueError('valid native RGBA frame required')
        if not isinstance(render_frame, dict) or not all(type(render_frame.get(k)) is int for k in
                ('referenceTimeNumerator', 'referenceTimeDenominator')) or render_frame['referenceTimeDenominator'] <= 0:
            raise ValueError('fresh native Fabric renderer receipt required')
        stamp = render_frame['referenceTimeNumerator'] / render_frame['referenceTimeDenominator']
        if stamp <= self.previous[0] or not all(
                type(v) in (int, float) and math.isfinite(v) for v in (render_time, sim_s, *pose)):
            raise ValueError('fresh finite renderer and physics receipt required')
        if render_time <= self.previous[1] or sim_s < self.previous[2] or len(pose) != 5:
            raise ValueError('fresh monotonic renderer and physics receipt required')
        self.process.stdin.write(rgba[:, :, :3].tobytes())
        self.receipts.write(json.dumps(dict(video_frame=self.frames, render_frame=render_frame,
            render_time=render_time, sim_s=sim_s, pose=pose)) + '\n')
        self.frames += 1
        self.previous = (stamp, render_time, sim_s)

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            close_error = None
            try:
                self.process.stdin.close()
            except (BrokenPipeError, OSError) as exc:
                close_error = exc
            try:
                code = self.process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
                raise RuntimeError('native video encoder timeout')
            if code != 0:
                raise RuntimeError(f'native video encoder failed: {code}')
            if close_error is not None:
                raise RuntimeError('native video encoder pipe failed') from close_error
            if self.frames < 2 or not self.path.is_file() or self.path.stat().st_size == 0:
                raise RuntimeError('native video has no usable frames')
        finally:
            self.receipts.close()
            self.errors.close()
