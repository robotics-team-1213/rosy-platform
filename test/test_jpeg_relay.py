"""Bench JPEG relay and compact recorder: host-testable parts, no rclpy or robot."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "deploy" / "robot" / "pinky_pro" / "dev"
RELAY = DEV / "jpeg_relay.py"
BASH = shutil.which("bash")

SPEC = importlib.util.spec_from_file_location("jpeg_relay", RELAY)
assert SPEC and SPEC.loader
relay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(relay)

CV2 = relay.resolve_encoder("cv2")


def _frame(h: int = 240, w: int = 320) -> np.ndarray:
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, : w // 2] = (255, 0, 0)  # blue left half in BGR
    img[:, w // 2 :] = (0, 0, 255)  # red right half in BGR
    return img


@pytest.mark.parametrize("backend", ["cv2", "auto"])
def test_bgr8_roundtrip_keeps_colour_order(backend: str) -> None:
    img = _frame()
    jpg = relay.encode_jpeg(img.tobytes(), 320, 240, 320 * 3, "bgr8", 85, relay.resolve_encoder(backend))
    assert jpg[:2] == b"\xff\xd8"
    out = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
    assert out.shape == (240, 320, 3)
    assert out[120, 40, 0] > 200 and out[120, 40, 2] < 50
    assert out[120, 280, 2] > 200 and out[120, 280, 0] < 50
    assert len(jpg) < img.nbytes // 5


def test_rgb8_is_converted_to_bgr_order() -> None:
    img = _frame()[:, :, ::-1].copy()  # same picture stored as RGB
    jpg = relay.encode_jpeg(img.tobytes(), 320, 240, 320 * 3, "rgb8", 85, CV2)
    out = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
    assert out[120, 40, 0] > 200  # left still blue once decoded as BGR


def test_mono8_and_row_padding() -> None:
    step = 328  # padded rows
    buf = np.full((240, step), 7, dtype=np.uint8)
    buf[:, :320] = 200
    jpg = relay.encode_jpeg(buf.tobytes(), 320, 240, step, "mono8", 85, CV2)
    out = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_GRAYSCALE)
    assert out.shape == (240, 320)
    assert abs(int(out.mean()) - 200) <= 2


def test_unsupported_encoding_raises() -> None:
    with pytest.raises(ValueError):
        relay.encode_jpeg(b"\0" * 12, 2, 2, 6, "yuv422", 85, CV2)


def test_encoder_is_resolved_once_and_injected() -> None:
    calls = []

    class Fake:
        IMWRITE_JPEG_QUALITY = 1

        @staticmethod
        def imencode(ext, img, params):
            calls.append((ext, img.shape, params))
            return True, np.frombuffer(b"\xff\xd8x", np.uint8)

    out = relay.encode_jpeg(b"\0" * 12, 2, 2, 6, "bgr8", 70, ("cv2", Fake))
    assert out == b"\xff\xd8x"
    assert calls == [(".jpg", (2, 2, 3), [1, 70])]


def test_decimator_default_passes_everything() -> None:
    d = relay.Decimator(0.0)
    assert all(d.accept(i * 0.01) for i in range(100))


def test_decimator_never_passes_back_to_back_after_a_gap() -> None:
    d = relay.Decimator(2.0)  # period 0.5 s, input 8 fps (0.125 s)
    assert d.accept(0.0)
    assert not d.accept(0.125)
    assert d.accept(0.9)  # late frame after a gap
    assert not d.accept(1.025)  # the next input frame must not follow it
    assert not d.accept(1.15)
    assert d.accept(1.4)


def test_decimator_caps_rate() -> None:
    d = relay.Decimator(2.0)
    kept = sum(d.accept(i / 8.0) for i in range(80))  # 10 s at 8 fps
    assert 19 <= kept <= 21


# --- rec_compact.sh contract (bash with PATH shims; no ROS, sudo, or robot) ---

needs_bash = pytest.mark.skipif(BASH is None, reason="bash is required for the recorder contract")


def _posix(p: Path) -> str:
    s = p.as_posix()
    if os.name == "nt" and len(s) > 1 and s[1] == ":":
        return "/" + s[0].lower() + s[2:]
    return s


def _write(p: Path, text: str) -> None:
    p.write_text(text, newline="\n")


def _env(tmp_path: Path, ros2_body: str, runtime_env: str) -> dict:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    py = _posix(Path(sys.executable))
    shims = {
        "sudo": '[ "$1" = -n ] && shift; exec "$@"',
        "setsid": 'exec "$@"',
        "python3": f'case "$1" in *jpeg_relay.py) exec sleep 300;; esac; exec "{py}" "$@"',
        "ros2": ros2_body,
    }
    for name, body in shims.items():
        _write(bin_dir / name, "#!/usr/bin/env bash\n" + body + "\n")
        (bin_dir / name).chmod(0o755)
    _write(tmp_path / "setup.bash", "true\n")
    _write(tmp_path / "runtime.env", runtime_env)
    env = dict(os.environ)
    env.update(
        PATH=f"{_posix(bin_dir)}:/usr/bin:/bin:{env.get('PATH', '')}",
        REC_ROOT=_posix(tmp_path / "rec"),
        REC_STATE=_posix(tmp_path / "state"),
        RUNTIME_ENV=_posix(tmp_path / "runtime.env"),
        ROS_SETUP=_posix(tmp_path / "setup.bash"),
        REC_START_WAIT="1",
        PROC_ROOT=_posix(tmp_path / "proc"),
    )
    return env


def _fake_proc(tmp_path: Path, pid: str, *argv: str) -> None:
    """The shims run as `sleep`, so each test states what /proc would show on the robot."""
    d = tmp_path / "proc" / pid
    d.mkdir(parents=True, exist_ok=True)
    (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")


def _state(tmp_path: Path) -> tuple[str, str]:
    bpid, rpid, _ = (tmp_path / "state").read_text().split(" ", 2)
    return bpid, rpid


def _stop(env: dict, tmp_path: Path) -> subprocess.CompletedProcess:
    if (tmp_path / "state").exists():
        bpid, rpid = _state(tmp_path)
        _fake_proc(tmp_path, bpid, "/usr/bin/python3", "/opt/ros/jazzy/bin/ros2", "bag", "record")
        _fake_proc(tmp_path, rpid, "python3", "/tmp/x/jpeg_relay.py", "--ns", "/pinky_t")
    return _rec(env, "stop")


def _kill(env: dict, *pids: str) -> None:
    subprocess.run([BASH, "-c", "kill -KILL " + " ".join(pids)], env=env, capture_output=True)


def _rec(env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([BASH, _posix(DEV / "rec_compact.sh"), *args],
                          # stop may legitimately wait 30 s (recorder) + 11 s (relay); Git bash under load is slow
                          capture_output=True, text=True, env=env, timeout=180)


def _sessions(tmp_path: Path) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted((tmp_path / "rec").glob("*/session.json"))]


def _alive(env: dict, pid: str) -> bool:
    return subprocess.run([BASH, "-c", f"kill -0 {pid}"], env=env, capture_output=True).returncode == 0


@needs_bash
def test_reason_with_quotes_is_data_not_code(tmp_path: Path) -> None:
    env = _env(tmp_path, "exec sleep 300", "ROSY_NAMESPACE=pinky_t\nROS_DOMAIN_ID=7\n")
    reason = "a'; import os; os.mkdir('PWNED'); x='\" ; touch PWNED2 #"
    started = _rec(env, "start", reason)
    try:
        assert started.returncode == 0, started.stdout + started.stderr
        (s,) = _sessions(tmp_path)
        assert s["reason"] == reason
        assert s["schema"] == "rosy.recording.session/1"
        assert "camera/front/compressed" in s["topics"] and "camera/front" not in s["topics"]
        assert s["ended_at"] is None
        bpid, rpid = _state(tmp_path)
    finally:
        stopped = _stop(env, tmp_path)
    assert stopped.returncode == 0, stopped.stdout + stopped.stderr
    assert _sessions(tmp_path)[0]["ended_at"]
    assert not _alive(env, bpid) and not _alive(env, rpid)
    assert not list(tmp_path.rglob("PWNED*")) and not list(Path.cwd().glob("PWNED*"))
    assert not (tmp_path / "state").exists()


@needs_bash
def test_empty_namespace_refuses_to_start(tmp_path: Path) -> None:
    env = _env(tmp_path, "exec sleep 300", "ROS_DOMAIN_ID=7\n")
    out = _rec(env, "start", "x")
    assert out.returncode == 1
    assert "ROSY_NAMESPACE" in out.stdout + out.stderr
    assert not list((tmp_path / "rec").glob("*"))


@needs_bash
def test_failed_start_marks_the_session_ended(tmp_path: Path) -> None:
    env = _env(tmp_path, "echo boom >&2; exit 1", "ROSY_NAMESPACE=pinky_t\n")
    env["REC_START_WAIT"] = "20"  # polled: returns as soon as the shim exits, even on a slow host
    out = _rec(env, "start", "x")
    assert out.returncode == 1
    (s,) = _sessions(tmp_path)
    assert s["ended_at"] and s["failure"]
    assert not (tmp_path / "state").exists()


@needs_bash
def test_stale_state_kills_the_old_relay(tmp_path: Path) -> None:
    env = _env(tmp_path, "exec sleep 300", "ROSY_NAMESPACE=pinky_t\n")
    old = subprocess.run([BASH, "-c", "sleep 300 >/dev/null 2>&1 & echo $!"],
                         capture_output=True, text=True, env=env)
    old_relay = old.stdout.strip()
    assert _alive(env, old_relay)
    _fake_proc(tmp_path, old_relay, "python3", "/tmp/x/jpeg_relay.py")
    _write(tmp_path / "state", f"999999 {old_relay} /nowhere\n")
    started = _rec(env, "start", "x")
    try:
        assert started.returncode == 0, started.stdout + started.stderr
        assert not _alive(env, old_relay)
    finally:
        _stop(env, tmp_path)
        _kill(env, old_relay)


@needs_bash
def test_reused_pids_from_state_are_never_signalled(tmp_path: Path) -> None:
    env = _env(tmp_path, "exec sleep 300", "ROSY_NAMESPACE=pinky_t\n")
    old = subprocess.run([BASH, "-c", "sleep 300 >/dev/null 2>&1 & echo $!; sleep 300 >/dev/null 2>&1 & echo $!"],
                         capture_output=True, text=True, env=env)
    foreign_b, foreign_r = old.stdout.split()
    _fake_proc(tmp_path, foreign_b, "/usr/lib/firefox")  # alive, but not a recorder
    _fake_proc(tmp_path, foreign_r, "sshd:", "rosy")  # alive, but not our relay
    try:
        _write(tmp_path / "state", f"{foreign_b} {foreign_r} /nowhere\n")
        started = _rec(env, "start", "x")  # stale state, not "already recording"
        assert started.returncode == 0, started.stdout + started.stderr
        assert _alive(env, foreign_b) and _alive(env, foreign_r)
        stopped = _stop(env, tmp_path)
        assert stopped.returncode == 0, stopped.stdout + stopped.stderr

        gone = tmp_path / "rec" / "gone"
        gone.mkdir()
        _write(tmp_path / "state", f"{foreign_b} {foreign_r} {_posix(gone)}\n")
        stopped = _rec(env, "stop")  # the recorded pids now belong to someone else
        assert stopped.returncode == 0, stopped.stdout + stopped.stderr
        assert _alive(env, foreign_b) and _alive(env, foreign_r)
    finally:
        _kill(env, foreign_b, foreign_r)
