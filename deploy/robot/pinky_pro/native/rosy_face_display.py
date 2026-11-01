"""rosy-face display loop: the boot-status view and FaceDisplay, the per-tick LCD, buzzer and lamp state machine (D-433; moved out of rosy-face.py by D-766)."""

from __future__ import annotations

import json
import re
import recovery_display
import signal
import time
import types
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Callable

from rosy_face_inputs import FaceFrames, core_owner, read_test_request, read_update, write_test_result
from rosy_face_parts import BatteryReader, Buzzer, LAMP_TEST_S, Lamp

try:  # the release's rule table (D-260); an older release has none
    from core_common import robot_state
except ImportError:
    robot_state = None
try:  # D-433: the screen's situation table and CORE's hand-over reader
    from core_common import face_screen
except ImportError:
    face_screen = None
try:  # the lamp, bar, expression and sound from one record (D-433 amendment 2026-10-09)
    from core_common import presentation
except ImportError:
    presentation = None

STATUS_DIR = "run/rosy-boot"
#: D-548: root's marker that this robot accepts the shared rosy-dev-* API tokens.
DEV_MODE_FILE = "etc/rosy/dev-mode"
LOGIN_CODE = re.compile(r"^[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4}-[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4}$")
LOGIN_ROLES = frozenset({"viewer", "operator", "administrator"})
#: D-433: CORE's hand-over (rosy-core's /run/rosy, 0644) and its writer's account.
FACE_INPUTS = "run/rosy/face-inputs.json"
#: D-483: CORE's pending peer-request approval code (rosy-core:rosy-display 2750, file 0640).
#: The code is a credential: drawn on the card, never logged.
PEER_APPROVAL = "run/rosy-peer-display/approval.json"
#: systemd-user-sessions writes it when the system goes down: SIGTERM then is a shutdown.
SHUTDOWN_MARK = "run/nologin"
BATTERY_INTERVAL_S = 15.0
BUZZER_REVERSE_S = 1.0
#: D-546: the recovering lamp and LCD line outlast the last RECOVERING tick by this long, so
#: they do not flicker between phases. The beep and an e-stop do not wait for it.
RECOVERY_HOLD_S = 1.5
#: Caution again inside this window stays silent (a battery near the threshold). Ready and
#: failed always sound on a real transition (review L2): they are the news a person waits for.
BUZZER_REPEAT_S = 300.0
REPEAT_LIMITED = frozenset({"caution"})
#: A caution (health or a CORE code) must hold this long before it sounds: a flapping one stays silent.
CAUTION_DEBOUNCE_S = 2.0
#: robot state -> sound; booting is silent.
#: Only for a release without core_common.presentation (tests pin it equal to presentation.SOUNDS).
SOUNDS = {"ready": "ready", "ready_held": "ready", "failed": "failed", "caution": "caution"}
#: robot state -> lamp_pattern argument (D-260 3). Fallback for a release without the
#: rule table; with it, the table also folds CORE's mode in (D-380, robot_state.lamp_pattern).
LAMP_PATTERNS = {"booting": "booting", "ready": "ready", "ready_held": "ready", "failed": "failed",
                 "caution": "caution"}
# D-260 / D-247 6: rosy-hw-test hands a buzzer or lamp test to this program while
# it owns the device. The request is root:rosy-display 0640 in /run/rosy-boot;
# the outcome goes to this unit's own runtime directory, which rosy-hw-test reads.
TEST_REQUEST = "run/rosy-boot/display-test.request"
TEST_RESULT = "run/rosy-display/display-test.json"
#: D-472 addendum 5: a blink may stand in for these normal patterns, moving or not. Booting,
#: failed, emergency, caution and blocked (D-381) always win: refused, or cut short.
IDENTIFY_OVER = frozenset({"ready", "manual", "navigating", "docking", "illumination"})


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def read_view(root: Path, battery: tuple[float, float] | None) -> dict:
    """What the card shows, from the indicator files and the last battery reading."""
    status = _read_json(root / STATUS_DIR / "boot-status.json")
    network = {key: value for key, value in _read_json(root / STATUS_DIR / "network.json").items()
               if key in {"mode", "ssid", "address", "epoch", "security"}}
    view = {
        "stage": status.get("stage") or "BOOTING",
        "failed_unit": status.get("failed_unit"),
        "detail": status.get("detail"),
        "device_name": status.get("device_name"),
        "release_id": status.get("release_id"),
        "ipv4": status.get("ipv4") or [],
        "api_port": status.get("api_port") or 8080,
        "network": network,
        "robot_mode": status.get("robot_mode"),
        "nav_state": status.get("nav_state"),
        "swarm_role": status.get("swarm_role"),
        "battery_percent": None if battery is None else round(battery[0]),
        "battery_voltage": None if battery is None else round(battery[1], 2),
    }
    if network.get("mode") == "ap" and network.get("security") != "open":
        try:
            lines = (root / STATUS_DIR / "ap-display.txt").read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            lines = []
        if len(lines) >= 2 and lines[1]:
            network["ssid"] = network.get("ssid") or lines[0]
            view["ap_login"] = lines[1]
    if view["stage"] == "CORE_READY":
        view.update(_login_view(root))
    view.update(_state_view(view, status))
    if (root / DEV_MODE_FILE).is_file():
        view["dev_mode"] = True
        if view.get("state_line"):
            view["state_line"] = "DEV " + view["state_line"]
    return view


def _state_view(view: dict, status: dict) -> dict:
    """D-260: the robot state, its LCD line and the top todo, from the shared rule table."""
    if robot_state is None:
        return {}
    devices = status.get("devices") if isinstance(status.get("devices"), list) else []
    mode = status.get("runtime_mode") if isinstance(status.get("runtime_mode"), str) else None
    # D-260 M1: CORE's live SAF-005 warning when rosy-boot-status copied it; else the table's default.
    warning = status.get("battery_warning_percent")
    if isinstance(warning, bool) or not isinstance(warning, (int, float)):
        warning = robot_state.BATTERY_WARNING_PERCENT
    result = robot_state.evaluate(view["stage"], devices, battery_percent=view["battery_percent"],
                                  battery_warning_percent=warning, runtime_mode=mode,
                                  failed_unit=view["failed_unit"],
                                  robot_mode=status.get("robot_mode"))
    todos = result["todos"]
    # D-380: the LCD line names the operating mode beside the health state — the
    # lamp shows it as a colour, the card says it in words. D-383: a formation
    # role rides at the end ("Ready - NAVIGATION - LEADER").
    line = (robot_state.state_line(result, lcd=True)
            + robot_state.mode_suffix(status.get("robot_mode"))
            + robot_state.role_suffix(status.get("swarm_role")))
    return {"robot_state": result["state"], "state_line": line,
            "todo": todos[0]["lcd"] if todos else None}


def _login_view(root: Path) -> dict:
    """D-193: the login line from rosy-login-code's hand-off; only well-formed values."""
    try:
        lines = (root / STATUS_DIR / "login-display.txt").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return {}
    if lines and lines[0] == "BURNED":
        return {"login_burned": True}
    if len(lines) >= 2 and LOGIN_CODE.fullmatch(lines[0]) and lines[1] in LOGIN_ROLES:
        return {"login_code": lines[0], "login_role": lines[1]}
    return {}


class FaceDisplay:
    """One poll: read the view, decide the screen, sound and light a new state; tick the face."""

    def __init__(self, root: Path, *, lcd, render: Callable[[dict], object], battery: BatteryReader,
                 buzzer: Buzzer, clock: Callable[[], float], lamp: Lamp | None = None,
                 wall: Callable[[], float] = time.time,
                 battery_interval: float = BATTERY_INTERVAL_S,
                 faces: FaceFrames | None = None,
                 strip: Callable[[object, str, str], object] | None = None,
                 core_owner: int | None = None, low_light_assist: bool = False) -> None:
        self.root = root
        self.lcd = lcd
        self._render = render
        self._battery = battery
        self._buzzer = buzzer
        self._lamp = lamp
        self._clock = clock
        self._wall = wall
        self._battery_interval = battery_interval
        self._battery_due: float | None = None
        self._battery_value: tuple[float, float] | None = None
        self._drawn: str | None = None
        self._state: str | None = None
        self._sounded: dict[str, float] = {}
        self._sound: str | None = None
        self._reversed_at: float | None = None
        self._caution_since: float | None = None
        self._held: tuple[str, float] | None = None
        self._tested: str | None = None
        self._faces = faces
        self._strip = strip
        self._core_owner = core_owner
        self._last_core: dict | None = None
        self._low_light_enabled = low_light_assist
        self._light_session = False
        self._mode: str | None = None
        self._drive_since: float | None = None
        self._testing: str | None = None
        self._testing_until = 0.0
        self._awake = True
        self._backlight = 100
        self._ticks = 0
        self.shutting_down = False
        self.animating: tuple | None = None
        self.screen: dict | None = None
        self.draws = 0
        self.frames = 0
        self.battery_reads = 0

    @staticmethod
    def robot_state_of(view: dict) -> str:
        """The rule table's state, or the stage alone on a release without the table."""
        if view.get("robot_state"):
            return str(view["robot_state"])
        kind = str(view["stage"]).split(":", 1)[0]
        return {"CORE_READY": "ready", "FAILED": "failed"}.get(kind, "booting")

    @staticmethod
    def _present(view: dict, state: str, core: dict | None, screen: dict | None):
        """The one record for lamp, bar, expression and sound (core_common.presentation). A release
        with the rule table but not the record gets the same fields from the old rules."""
        if robot_state is not None and presentation is not None:
            return presentation.present(state=state, robot_mode=view.get("robot_mode"),
                                        nav_state=view.get("nav_state"), core=core, screen=screen,
                                        battery_percent=view.get("battery_percent"))
        lamp = LAMP_PATTERNS.get(state)
        if robot_state is not None:
            args = (state, (core or {}).get("robot_mode") or view.get("robot_mode"),
                    (core or {}).get("nav_state") or view.get("nav_state"))
            recovery = (core or {}).get("recovery")
            signal = (core or {}).get("signal")
            try:
                lamp = robot_state.lamp_pattern(*args, recovery, signal)
            except TypeError:  # before the turn signal, then before D-546's recovery argument
                try:
                    lamp = robot_state.lamp_pattern(*args, recovery)
                except TypeError:
                    lamp = robot_state.lamp_pattern(*args)
        bar = None if not screen or screen["kind"] != "face" else (
            screen["face"], screen["strip"] or "", "caution" if screen["strip_tone"] == "caution" else "ok", None, None)
        return types.SimpleNamespace(
            state=state, lamp=lamp, bar=bar, sound="emergency" if lamp == "emergency" else SOUNDS.get(state),
            reversing=bool(core) and core.get("estop") is False and lamp == "recovering"
            and core.get("recovery") == "retrace")

    @staticmethod
    def lamp_pattern_for(view: dict, state: str, core: dict | None = None) -> str | None:
        return FaceDisplay._present(view, state, core, None).lamp

    def _announce(self, sound: str | None, now: float) -> None:
        """Sound ``pres.sound`` on a change (D-381: the e-stop alarm replaces the health sound; ready and
        held ready are one sound). A caution must hold CAUTION_DEBOUNCE_S first; caution, and the ready that
        follows it, repeat at most every BUZZER_REPEAT_S. The e-stop, failed and the ready after them always sound."""
        if sound == "caution":
            self._caution_since = now if self._caution_since is None else self._caution_since
            if now - self._caution_since < CAUTION_DEBOUNCE_S:
                return  # not yet a caution: self._sound keeps the sound it had
        else:
            self._caution_since = None
        previous, self._sound = self._sound, sound
        if sound is None or sound == previous:
            return
        last = self._sounded.get(sound)
        # ready is limited only when it follows a caution (the flapping case); after an e-stop or a failure it is news.
        if ((sound in REPEAT_LIMITED or (sound == "ready" and previous == "caution"))
                and last is not None and now - last < BUZZER_REPEAT_S):
            return
        self._sounded[sound] = now
        self._buzzer.announce(sound)

    def handle_test(self) -> str | None:
        """Play a D-247 test rosy-hw-test handed over; each request id once. The state played, or None."""
        request = read_test_request(self.root / TEST_REQUEST, self._wall())
        if request is None or request["request_id"] == self._tested:
            return None
        def unsafe_identity() -> str | None:
            # D-472 5: e-stop, fault, caution or no CORE hand-over: the safety display wins.
            # The pattern is recomputed from the files (the lamp's own is None mid-blink).
            # D-596 rev 2026-10-10: the answer is the refusal reason CORE hands on to Fleet.
            core = self._core()
            if core is None or core.get("estop") is not False or core.get("caution"):
                return "CORE_UNAVAILABLE" if core is None else "CAUTION_ACTIVE" if core.get("estop") is False else "ESTOP"
            view = read_view(self.root, self._battery_value)
            pattern = self.lamp_pattern_for(view, self.robot_state_of(view), core)
            return None if pattern in IDENTIFY_OVER else "CAUTION_ACTIVE" if pattern == "caution" else "STATE_DISPLAY"
        identifying = request["action"].startswith("identify_")
        identify_ready = identifying and self._lamp is not None and self._lamp.available(for_identify=True)
        refused = identifying and ("LAMP_UNAVAILABLE" if not identify_ready else unsafe_identity())
        if refused:
            # Answered at once, so rosy-hw-test does not wait out its hand-over timeout.
            self._tested = request["request_id"]
            state = "failed" if identify_ready else "unavailable"
            write_test_result(self.root / TEST_RESULT, json.dumps(
                {"schema": 1, "request_id": request["request_id"], "action": request["action"],
                 "state": state, "detail": "안전·상태 표시가 우선 — 식별 점멸 거절", "reason": refused},
                ensure_ascii=False, sort_keys=True) + "\n")
            return state
        if self._lamp is not None and self._lamp.pattern in ("emergency", "failed", "caution", "recovering", "bridging"):
            return None
        if self.screen and (self.screen["kind"] in ("stopped", "update", "shutdown")
                            or self.screen["row"] == "failed" or self.screen.get("strip_tone") == "caution"):
            return None  # Alarm outputs must never wait for a blocking bench test.
        if self._lamp is not None and self._light_session:
            self._lamp.show(None)
        self._tested = request["request_id"]
        # D-433 row 10: the strip names the test while it plays.
        self._testing, self._testing_until = request["action"], self._clock() + LAMP_TEST_S
        if request["action"] == "buzzer":
            state, detail = self._buzzer.test()
        elif self._lamp is not None and request["action"].startswith("identify_"):
            # Once at accept, never for D-596 identify_<colour>_quiet; self._sound stays the health sound.
            if not request["action"].endswith("_quiet"):
                self._buzzer.announce("call")
            state, detail = self._lamp.identify(request["action"][9:].removesuffix("_quiet"), unsafe_identity)
        elif self._lamp is not None:
            state, detail = self._lamp.test()
        else:
            state, detail = "unavailable", "부팅 표시에 램프가 없음"
        write_test_result(self.root / TEST_RESULT, json.dumps(
            {"schema": 1, "request_id": request["request_id"], "action": request["action"],
             "state": state, "detail": detail}, ensure_ascii=False, sort_keys=True) + "\n")
        return state

    def _core(self) -> dict | None:
        """CORE's face hand-over with D-546's recovery hold: an e-stop clears ``recovery`` at
        once; a phase that just ended is held 1.5 s as ``return`` (lamp and LCD, no beep)."""
        core = self._read_core()
        if core is None:
            return None
        now = self._clock()
        phase = core.get("recovery")
        if core.get("estop") is not False:
            self._held = None
            return {**core, "recovery": None} if phase else core
        if phase:
            self._held = (phase, now)
        elif self._held and now - self._held[1] < RECOVERY_HOLD_S:
            return {**core, "recovery": "return" if self._held[0] == "retrace" else self._held[0]}
        else:
            self._held = None
        return core

    def _read_core(self) -> dict | None:
        """CORE's face hand-over, strictly read; None when missing, stale or not CORE's."""
        if face_screen is None:
            return None
        wall = self._wall()
        now = datetime.fromtimestamp(wall, timezone.utc)
        core = face_screen.read_face_inputs(str(self.root / FACE_INPUTS), now, owner_uid=self._core_owner)
        if core is not None:
            self._last_core = core
            return core
        # One unreadable poll (a write in flight, a short read) is not a dead CORE:
        # keep the last good hand-over until it is FACE_INPUTS_FRESH_S old.
        last = self._last_core
        if last is not None and wall - last["written_ts"] <= face_screen.FACE_INPUTS_FRESH_S:
            return last
        self._last_core = None
        return None

    def screen_of(self, view: dict, now: float) -> dict | None:
        """D-433: the situation table's answer for this poll (None on a release without it)."""
        if face_screen is None or robot_state is None:
            return None
        core = self._core()
        mode = core.get("robot_mode") if core else None
        if mode != self._mode:  # the drive card's cadence starts with each operating mode
            self._mode = mode
            self._drive_since = now if mode in robot_state.OPERATING_MODES else None
        login = "code" if view.get("login_code") else ("burned" if view.get("login_burned") else None)
        # D-483: a release without the reader has no peer row in its table either.
        extra = {}
        if hasattr(face_screen, "read_peer_approval"):
            extra["peer"] = face_screen.read_peer_approval(
                str(self.root / PEER_APPROVAL), datetime.fromtimestamp(self._wall(), timezone.utc),
                owner_uid=self._core_owner)
        quality = core.get("camera_quality") if core else None
        expires = core.get("camera_quality_until") if core else None
        fresh = quality is not None and expires is not None and self._wall() <= expires
        if not self._low_light_enabled or not fresh or quality.get("reason") == "overexposed":
            self._light_session = False
        elif quality.get("valid") is False and quality.get("reason") == "low_light":
            self._light_session = True
        screen = face_screen.screen_for(
            stage=view["stage"], state=self.robot_state_of(view), todo=view.get("todo"),
            ap_mode=(view.get("network") or {}).get("mode") == "ap", login=login, core=core,
            update=read_update(self.root, self._wall()),
            test=self._testing if now < self._testing_until else None,
            shutting_down=self.shutting_down, drive_since=self._drive_since, now=now,
            light_assist=self._light_session, **extra)
        if screen["kind"] != "light":
            self._light_session = False
        if (screen["kind"] == "status" and screen.get("row") in {"failed", "ap", "booting"}
                and not (core and (core.get("estop") or core.get("robot_mode") == "EMERGENCY"))):
            if page := recovery_display.read_page(self.root, view, now):
                screen = {**screen, "row": "network_recovery", "recovery_page": page}
        return screen

    def _lcd_call(self, name: str, *args) -> None:
        action = getattr(self.lcd, name, None)
        if action is not None:
            action(*args)

    def _power(self, screen: dict | None) -> None:
        """Panel sleep and backlight follow the table (D-385 4: standby is dark)."""
        if self.lcd is None:
            return
        awake = screen["awake"] if screen else True
        backlight = screen["backlight"] if screen else 100
        if awake != self._awake:
            self._lcd_call("wake" if awake else "sleep")
            self._awake = awake
            if awake:
                self._drawn = None  # redraw what the sleeping panel stopped showing
        if backlight != self._backlight:
            self._lcd_call("set_backlight", backlight)
            self._backlight = backlight

    def step(self) -> bool:
        """True when the LCD was redrawn."""
        now = self._clock()
        if self.shutting_down:
            # Review LOW: the last poll only draws the shutdown card — no battery read,
            # no sound, no lamp, no handed-over test on the way out.
            return self._draw_shutdown(now)
        if self._battery_due is None or now >= self._battery_due:
            self._battery_value = self._battery.read()
            self.battery_reads += 1
            self._battery_due = now + self._battery_interval
        view = read_view(self.root, self._battery_value)
        # D-385: 기다리는 동안 무대 제목이 1 fps 로 숨쉰다 — 끝난 상태는 고요히 그대로.
        if str(view["stage"]).split(":", 1)[0] in ("BOOTING", "PROVISIONED"):
            view["frame"] = int(now) % 2
        state = self.robot_state_of(view)
        if state != self._state:
            self._state = state
        core = self._core()
        screen = self.screen = self.screen_of(view, now)
        pres = self._present(view, state, core, screen)
        pattern = pres.lamp
        if self._lamp is not None:
            # D-380: a mode change switches the pattern without a sound; show() is
            # idempotent, so an unchanged pattern costs nothing.
            self._lamp.show(pattern)
            self._lamp.poll()
        if self.handle_test() is not None:
            screen = self.screen = self.screen_of(view, now)
        self._power(screen)
        kind = screen["kind"] if screen else "status"
        redrawn = False
        bar = pres.bar  # None without the presentation record (a mixed install)
        if bar is not None and view.get("dev_mode"):  # D-548: DEV on every face frame and card bar
            bar = (bar[0], f"DEV {bar[1]}" if bar[1] else "DEV MODE", *bar[2:])
        if kind == "face" and screen["overlay"] is None:
            # The face plays from tick(); the status bar rides every frame.
            self.animating = bar
            self._drawn = None
        else:
            self.animating = None
            if kind == "sleep":
                self._drawn = "sleep"
            else:
                card = dict(view)
                if screen is not None:
                    card["screen"] = screen
                    if kind == "face":
                        card["bar"] = bar[1:] if bar is not None else None
                    if screen.get("line"):
                        card["state_line"] = screen["line"]  # D-433 row 7: CORE not responding
                    if kind == "update":
                        card["frame"] = int(now) % 2
                key = json.dumps(card, sort_keys=True)
                if key != self._drawn and self.lcd is not None:
                    try:
                        self.lcd.img_show(self._render(card))
                    except Exception:
                        # A broken LCD must not swallow the entry alarm.
                        self._announce(pres.sound, now)
                        raise
                    self._drawn = key
                    self.draws += 1
                    redrawn = True
        # A synchronous buzzer pattern can last hundreds of milliseconds. Show
        # the lamp and any status card first, especially on emergency entry.
        self._announce(pres.sound, now)
        self._reverse_alarm(pres.reversing, now)
        return redrawn

    def _reverse_alarm(self, reversing: bool, now: float) -> None:
        """D-546: one reversing beep per BUZZER_REVERSE_S while ``Presentation.reversing``; silent otherwise."""
        if not reversing:
            self._reversed_at = None
        elif self._reversed_at is None or now - self._reversed_at >= BUZZER_REVERSE_S:
            self._reversed_at = now
            self._buzzer.announce("reverse")

    def _draw_shutdown(self, now: float) -> bool:
        view = read_view(self.root, self._battery_value)
        screen = face_screen.screen_for(shutting_down=True) if face_screen is not None else None
        self.animating = None
        if screen is None or self.lcd is None:
            return False
        self._power(screen)
        card = {**view, "screen": screen,
                "shutdown_title": ("Shutting down" if (self.root / SHUTDOWN_MARK).exists()
                                   else "Display restarting")}
        self.lcd.img_show(self._render(card))
        self.draws += 1
        return True

    def tick(self) -> bool:
        """Push the next face frame while the face owns the screen. True when one was drawn."""
        if self.animating is None or self.lcd is None or self._faces is None:
            return False
        self._ticks += 1
        if self._backlight < 100 and self._ticks % 2:
            return False  # D-185: the dimmed (idle) face plays at half rate
        face, *bar = self.animating
        frame = self._faces.next(face)
        if frame is None:
            return False
        if self._strip is not None:
            frame = self._strip(frame, *bar)
        self.lcd.show_panel(frame)
        self.frames += 1
        return True
