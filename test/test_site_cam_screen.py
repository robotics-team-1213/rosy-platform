import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "deploy/site/rosy_cam_screen.py"


def load():
    spec = importlib.util.spec_from_file_location("cam_screen", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Commands:
    def __init__(self, devices, identities, mdns="", avahi="", connected=None):
        self.devices = devices
        self.identities = identities
        self.mdns = mdns
        self.avahi = avahi
        self.connected = connected
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        assert kwargs["timeout"] == 10
        assert "shell" not in kwargs
        if args[0] == "avahi-browse":
            out = self.avahi
        elif args[1:] == ["devices"]:
            out = "List of devices attached\n" + self.devices
        elif args[1:] == ["mdns", "services"]:
            out = self.mdns
        elif args[1] == "connect":
            if self.connected is not None:
                self.devices = self.connected
            out = "connected"
        elif args[3:5] == ["shell", "getprop"]:
            out = self.identities[args[2]][args[5]]
        elif args[3:] == ["shell", "dumpsys", "power"]:
            out = "mWakefulness=Dozing\n"
        elif args[3:] == ["shell", "input", "keyevent", "KEYCODE_WAKEUP"]:
            out = ""
        else:
            raise AssertionError(args)
        return subprocess.CompletedProcess(args, 0, out, "")


CONFIG = {"adb_path": "/opt/platform-tools/adb", "expected_serial": "PHONE123", "expected_model": "SM-G991N"}


def identity(serial="PHONE123", model="SM-G991N"):
    return {"ro.serialno": serial, "ro.product.model": model}


def test_wake_targets_verified_phone_only():
    module = load()
    runner = Commands("phone:34567\tdevice\nother:34568\tdevice\n", {
        "phone:34567": identity(), "other:34568": identity("OTHER", "Tablet")})
    result = module.execute(CONFIG, "wake", runner)
    assert result["status"] == "wake_sent"
    assert runner.calls[-1] == [CONFIG["adb_path"], "-s", "phone:34567", "shell", "input", "keyevent", "KEYCODE_WAKEUP"]


@pytest.mark.parametrize("rows,identities", [
    ("phone\tdevice\n", {"phone": identity(model="Wrong")}),
    ("one\tdevice\ntwo\tdevice\n", {"one": identity(), "two": identity()}),
    ("phone\tunauthorized\n", {}),
])
def test_untrusted_or_ambiguous_never_wakes(rows, identities):
    module = load()
    runner = Commands(rows, identities)
    with pytest.raises(module.ScreenError):
        module.execute(CONFIG, "wake", runner)
    assert not any("keyevent" in call for call in runner.calls)


@pytest.mark.parametrize("discovery", ["adb", "avahi"])
def test_dynamic_port_reconnect_then_verify(discovery):
    module = load()
    runner = Commands("", {"192.0.2.10:45678": identity()},
        mdns="adb-PHONE123-guid _adb-tls-connect._tcp 192.0.2.10:45678\n" if discovery == "adb" else "",
        avahi="=;eth0;IPv4;adb-PHONE123-guid;_adb-tls-connect._tcp;local;phone.local;192.0.2.10;45678;\n" if discovery == "avahi" else "",
        connected="192.0.2.10:45678\tdevice\n")
    result = module.execute(CONFIG, "status", runner)
    assert result == {"status": "connected", "model": "SM-G991N", "screen": "Dozing"}
    assert [CONFIG["adb_path"], "connect", "192.0.2.10:45678"] in runner.calls
    assert not any("keyevent" in call for call in runner.calls)


def test_advertisement_does_not_replace_actual_identity():
    module = load()
    runner = Commands("", {"192.0.2.10:45678": identity("IMPOSTOR")},
        mdns="adb-PHONE123-guid _adb-tls-connect._tcp 192.0.2.10:45678\n",
        connected="192.0.2.10:45678\tdevice\n")
    with pytest.raises(module.ScreenError):
        module.execute(CONFIG, "wake", runner)
    assert not any("keyevent" in call for call in runner.calls)


def test_unknown_advertisement_not_connected():
    module = load()
    runner = Commands("", {}, mdns="adb-PHONE123OTHER-guid _adb-tls-connect._tcp 192.0.2.10:45678\n")
    with pytest.raises(module.ScreenError):
        module.execute(CONFIG, "wake", runner)
    assert not any("connect" in call for call in runner.calls)


def test_timeout_never_wakes():
    module = load()
    def timeout(args, **kwargs):
        raise subprocess.TimeoutExpired(args, 10)
    with pytest.raises(module.ScreenError):
        module.execute(CONFIG, "wake", timeout)


def test_duplicate_dynamic_connections_refused():
    module = load()
    runner = Commands("", {"192.0.2.10:45678": identity(), "192.0.2.10:45679": identity()},
        mdns="adb-PHONE123-one _adb-tls-connect._tcp 192.0.2.10:45678\nadb-PHONE123-two _adb-tls-connect._tcp 192.0.2.10:45679\n",
        connected="192.0.2.10:45678\tdevice\n192.0.2.10:45679\tdevice\n")
    with pytest.raises(module.ScreenError):
        module.execute(CONFIG, "wake", runner)
    assert not any("keyevent" in call for call in runner.calls)


@pytest.mark.parametrize("failed_step", ["connect", "getprop"])
def test_stale_port_then_live_duplicate_service(failed_step):
    module = load()
    runner = Commands("", {"192.0.2.10:42029": identity()},
        avahi="=;eth0;IPv4;adb-PHONE123-guid;_adb-tls-connect._tcp;local;phone.local;192.0.2.10;34747;\n"
              r"=;eth0;IPv4;adb-PHONE123-guid\032\0402\041;_adb-tls-connect._tcp;local;phone.local;192.0.2.10;42029;" + "\n",
        connected="192.0.2.10:42029\tdevice\n")
    def stale(args, **kwargs):
        if (args[1:] == ["connect", "192.0.2.10:34747"] or
                (len(args) > 2 and args[2] == "192.0.2.10:34747")):
            runner.calls.append(args)
            if failed_step == "getprop" and args[1] == "connect":
                return subprocess.CompletedProcess(args, 0, "connected", "")
            return subprocess.CompletedProcess(args, 1, "", "private failure")
        return runner(args, **kwargs)
    result = module.execute(CONFIG, "wake", stale)
    assert result["status"] == "wake_sent"
    assert runner.calls[-1][2] == "192.0.2.10:42029"


def test_stop_after_first_unique_verified_connection():
    module = load()
    runner = Commands("", {"192.0.2.10:34747": identity()},
        mdns="adb-PHONE123-one _adb-tls-connect._tcp 192.0.2.10:34747\nadb-PHONE123-two _adb-tls-connect._tcp 192.0.2.10:42029\n",
        connected="192.0.2.10:34747\tdevice\n")
    assert module.execute(CONFIG, "wake", runner)["status"] == "wake_sent"
    assert [CONFIG["adb_path"], "connect", "192.0.2.10:42029"] not in runner.calls


def test_public_example_can_be_loaded_without_real_identity():
    module = load()
    config = json.loads(SCRIPT.with_name("cam-screen.json.example").read_text())
    assert module.validate(config) == config
    assert config["expected_serial"] == "YOURPHONESERIAL"


PACKAGE = "io.github.livsbittt.rosy.cam"
STATE = {"running": True, "light_supported": True, "light_requested": False,
         "torch_on": False, "dark": True, "light_limited": False,
         "photo_saving": False, "photo_saved": False, "photo_failed": False}


def ui(text="request", duplicate=False, package=PACKAGE, bounds="[20,40][300,100]"):
    text = "\ucd2c\uc601 \uc870\uba85 \uc694\uccad" if text == "request" else text
    node = (f'<node package="{package}" text="{text}" clickable="true" '
            f'enabled="true" bounds="{bounds}"/>')
    return '<hierarchy>' + node * (2 if duplicate else 1) + '</hierarchy>'


class LightCommands(Commands):
    def __init__(self, state=None, xml=None, showing=False, secure=False):
        super().__init__("phone\tdevice\n", {"phone": identity()})
        self.state = dict(STATE if state is None else state)
        self.xml = ui() if xml is None else xml
        self.showing = showing
        self.secure = secure
        self.tap_count = 0

    def __call__(self, args, **kwargs):
        shell = args[3:]
        if shell[:3] == ["shell", "dumpsys", "activity"]:
            out = 'rosy_cam_state=' + json.dumps(self.state) + '\n'
        elif shell == ["shell", "dumpsys", "window", "policy"]:
            out = ('KeyguardServiceDelegate\n  showing=' + str(self.showing).lower()
                   + '\n  secure=' + str(self.secure).lower() + '\n')
        elif shell == ["shell", "wm", "size"]:
            out = 'Physical size: 1080x2400\n'
        elif shell == ["shell", "dumpsys", "window", "displays"]:
            out = ('mCurrentFocus=Window{abc u0 ' + PACKAGE + '/.MainActivity}\n'
                   'mFocusedApp=ActivityRecord{def u0 ' + PACKAGE + '/.MainActivity t224}\n')
        elif shell[:3] == ["shell", "uiautomator", "dump"]:
            out = 'UI hierchary dumped to: ' + shell[3]
        elif shell[:2] == ["shell", "cat"]:
            out = self.xml
        elif shell[:2] == ["shell", "rm"]:
            out = ''
        elif shell[:3] == ["shell", "am", "start"]:
            out = 'Status: ok'
        elif shell[:3] == ["shell", "wm", "dismiss-keyguard"]:
            self.showing = False
            out = ''
        elif shell[:3] == ["shell", "input", "tap"]:
            self.tap_count += 1
            self.state['light_requested'] = not self.state['light_requested']
            out = ''
        else:
            return super().__call__(args, **kwargs)
        self.calls.append(args)
        return subprocess.CompletedProcess(args, 0, out, '')


def test_light_status_is_read_only_and_reports_actual_torch():
    runner = LightCommands()
    result = load().execute(CONFIG, 'light-status', runner)
    assert result['light_requested'] is False
    assert result['torch_on'] is False
    assert not any('keyevent' in c or 'tap' in c or 'start' in c for c in runner.calls)


def test_request_uses_official_ui_and_confirms_flag_not_torch():
    runner = LightCommands()
    result = load().execute(CONFIG, 'light-request', runner)
    assert result['light_requested'] is True
    assert result['torch_on'] is False
    assert runner.tap_count == 1
    assert any('KEYCODE_WAKEUP' in c for c in runner.calls)


@pytest.mark.parametrize('action,requested', [('light-request', True), ('light-cancel', False)])
def test_existing_request_never_renews_and_inactive_cancel_is_noop(action, requested):
    runner = LightCommands({**STATE, 'light_requested': requested})
    load().execute(CONFIG, action, runner)
    assert runner.tap_count == 0
    assert not any('KEYCODE_WAKEUP' in c for c in runner.calls)


@pytest.mark.parametrize('changes', [{'running': False}, {'light_supported': False},
                                      {'light_limited': True}, {'running': 'true'}])
def test_light_request_refuses_unavailable_or_unknown_state(changes):
    runner = LightCommands({**STATE, **changes})
    module = load()
    with pytest.raises(module.ScreenError):
        module.execute(CONFIG, 'light-request', runner)
    assert runner.tap_count == 0
    assert not any('KEYCODE_WAKEUP' in c for c in runner.calls)


@pytest.mark.parametrize('xml', [ui(duplicate=True), ui(package='another.app'),
                                 ui(bounds='[-1,40][300,100]'), ui(bounds='[20,40][1200,100]')])
def test_ambiguous_untrusted_or_invalid_ui_never_tapped(xml):
    runner = LightCommands(xml=xml)
    module = load()
    with pytest.raises(module.ScreenError):
        module.execute(CONFIG, 'light-request', runner)
    assert runner.tap_count == 0


def test_secure_keyguard_not_dismissed_or_tapped():
    runner = LightCommands(showing=True, secure=True)
    module = load()
    with pytest.raises(module.ScreenError):
        module.execute(CONFIG, 'light-request', runner)
    assert runner.tap_count == 0
    assert not any('dismiss-keyguard' in c for c in runner.calls)


def test_nonsecure_keyguard_normal_dismissal_then_cancel():
    runner = LightCommands({**STATE, 'light_requested': True},
                           xml=ui(text='\uc870\uba85 \uc694\uccad \ucde8\uc18c'), showing=True)
    result = load().execute(CONFIG, 'light-cancel', runner)
    assert result['light_requested'] is False
    assert runner.tap_count == 1
    assert any('dismiss-keyguard' in c for c in runner.calls)


@pytest.mark.parametrize('bad', ['missing', 'duplicate', 'unknown', 'wrong-type'])
def test_invalid_diagnostics_refused_without_ui_actions(bad):
    module = load()
    runner = LightCommands()
    def invalid(args, **kwargs):
        if args[3:6] == ['shell', 'dumpsys', 'activity']:
            runner.calls.append(args)
            state = dict(STATE)
            if bad == 'unknown': state['new_field'] = False
            if bad == 'wrong-type': state['torch_on'] = 1
            raw = 'rosy_cam_state=' + json.dumps(state) + '\n'
            if bad == 'missing': raw = 'No running service\n'
            if bad == 'duplicate': raw *= 2
            return subprocess.CompletedProcess(args, 0, raw, '')
        return runner(args, **kwargs)
    with pytest.raises(module.ScreenError):
        module.execute(CONFIG, 'light-status', invalid)
    assert runner.tap_count == 0
    assert not any('keyevent' in c for c in runner.calls)


def test_ui_change_between_fresh_dumps_refused():
    module = load()
    runner = LightCommands()
    dumps = 0
    def changed(args, **kwargs):
        nonlocal dumps
        if args[3:5] == ['shell', 'cat']:
            dumps += 1
            if dumps == 2: runner.xml = ui(bounds='[400,40][700,100]')
        return runner(args, **kwargs)
    with pytest.raises(module.ScreenError):
        module.execute(CONFIG, 'light-request', changed)
    assert runner.tap_count == 0


def test_late_thermal_limit_refuses_before_tap():
    module = load()
    runner = LightCommands()
    reads = 0
    def limited(args, **kwargs):
        nonlocal reads
        if args[3:6] == ['shell', 'dumpsys', 'activity']:
            reads += 1
            if reads == 2: runner.state['light_limited'] = True
        return runner(args, **kwargs)
    with pytest.raises(module.ScreenError):
        module.execute(CONFIG, 'light-request', limited)
    assert runner.tap_count == 0


def test_request_that_became_active_is_not_renewed_at_tap():
    runner = LightCommands()
    reads = 0
    def active(args, **kwargs):
        nonlocal reads
        if args[3:6] == ['shell', 'dumpsys', 'activity']:
            reads += 1
            if reads == 2: runner.state['light_requested'] = True
        return runner(args, **kwargs)
    assert load().execute(CONFIG, 'light-request', active)['status'] == 'unchanged'
    assert runner.tap_count == 0


def test_compose_button_text_uses_only_own_clickable_parent():
    label = ui().split('text="')[1].split('"', 1)[0]
    runner = LightCommands(xml=(f'<hierarchy><node package="{PACKAGE}" clickable="true" enabled="true" bounds="[10,30][320,110]">'
                                f'<node package="{PACKAGE}" text="{label}" clickable="false" enabled="true" bounds="[20,40][300,100]"/>'
                                '</node></hierarchy>'))
    assert load().execute(CONFIG, 'light-request', runner)['light_requested'] is True
    assert runner.calls[-2][3:6] == ['shell', 'input', 'tap']
    assert runner.calls[-2][6:] == ['160', '70']  # Visible label, not the parent's center.


def test_scroll_only_unique_owned_viewport_then_fresh_button():
    runner = LightCommands(xml=(f'<hierarchy><node package="{PACKAGE}" scrollable="true" enabled="true" bounds="[10,30][1000,2300]"/></hierarchy>'))
    def scrolled(args, **kwargs):
        if args[3:6] == ['shell', 'input', 'swipe']:
            runner.calls.append(args)
            assert args[6:] == ['505', '2280', '505', '50', '300']
            runner.xml = ui()
            return subprocess.CompletedProcess(args, 0, '', '')
        return runner(args, **kwargs)
    assert load().execute(CONFIG, 'light-request', scrolled)['light_requested'] is True
    assert runner.tap_count == 1


@pytest.mark.parametrize('kind', ['foreign-focus', 'unknown-keyguard', 'stale-file', 'foreign-scroll'])
def test_untrusted_context_cannot_tap(kind):
    module = load()
    runner = LightCommands()
    if kind == 'foreign-scroll':
        runner.xml = '<hierarchy><node package="another.app" scrollable="true" enabled="true" bounds="[10,30][1000,2300]"/></hierarchy>'
    def untrusted(args, **kwargs):
        shell = args[3:]
        if (kind == 'foreign-focus' and shell == ['shell', 'dumpsys', 'window', 'displays']):
            return subprocess.CompletedProcess(args, 0, 'mCurrentFocus=Window{abc u0 another.app/.MainActivity}', '')
        if kind == 'unknown-keyguard' and shell == ['shell', 'dumpsys', 'window', 'policy']:
            return subprocess.CompletedProcess(args, 0, 'KeyguardServiceDelegate\n  showing=false\n', '')
        if kind == 'stale-file' and shell[:3] == ['shell', 'uiautomator', 'dump']:
            return subprocess.CompletedProcess(args, 0, 'ERROR: could not get idle state', '')
        return runner(args, **kwargs)
    with pytest.raises(module.ScreenError):
        module.execute(CONFIG, 'light-request', untrusted)
    assert runner.tap_count == 0


def test_unconfirmed_tap_never_claims_requested_or_torch(monkeypatch):
    module = load()
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)
    runner = LightCommands()
    def not_applied(args, **kwargs):
        result = runner(args, **kwargs)
        if args[3:6] == ['shell', 'input', 'tap']:
            runner.state['light_requested'] = False
        return result
    with pytest.raises(module.ScreenError):
        module.execute(CONFIG, 'light-request', not_applied)
    assert runner.tap_count == 1


class DisplaysCommands(LightCommands):
    """Android 15 exposes focus in displays, with shade above a resumed activity."""
    def __init__(self, focus='camera', focused_app=PACKAGE + '/.MainActivity', sticky=False):
        super().__init__()
        self.focus = focus
        self.focused_app = focused_app
        self.sticky = sticky

    def __call__(self, args, **kwargs):
        shell = args[3:]
        if shell == ['shell', 'dumpsys', 'window', 'windows']:
            self.calls.append(args)
            return subprocess.CompletedProcess(args, 0, 'No focus fields here\n', '')
        if shell == ['shell', 'dumpsys', 'window', 'displays']:
            self.calls.append(args)
            component = PACKAGE + '/.MainActivity' if self.focus == 'camera' else self.focus
            out = ('mCurrentFocus=Window{d168224 u0 ' + component + '}\n'
                   'mFocusedApp=ActivityRecord{5f088c5 u0 ' + self.focused_app + ' t224}\n')
            return subprocess.CompletedProcess(args, 0, out, '')
        if shell == ['shell', 'input', 'keyevent', 'KEYCODE_BACK']:
            self.calls.append(args)
            if not self.sticky: self.focus = 'camera'
            return subprocess.CompletedProcess(args, 0, '', '')
        return super().__call__(args, **kwargs)


def test_android15_displays_focus_is_supported():
    runner = DisplaysCommands()
    assert load().execute(CONFIG, 'light-request', runner)['light_requested'] is True
    assert runner.tap_count == 1


def test_known_notification_shade_closed_once_above_camera(monkeypatch):
    module = load()
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)
    runner = DisplaysCommands(focus='NotificationShade')
    assert module.execute(CONFIG, 'light-request', runner)['light_requested'] is True
    assert sum('KEYCODE_BACK' in c for c in runner.calls) == 1
    assert sum(c[3:6] == ['shell', 'am', 'start'] for c in runner.calls) == 2
    assert runner.tap_count == 1


@pytest.mark.parametrize('focus,app', [
    ('NotificationShade', 'other.app/.MainActivity'),
    ('other.app/.Dialog', PACKAGE + '/.MainActivity'),
    ('camera', 'other.app/.MainActivity'),
])
def test_unknown_overlay_or_unrelated_focused_activity_never_closed(focus, app):
    module = load()
    runner = DisplaysCommands(focus=focus, focused_app=app)
    with pytest.raises(module.ScreenError):
        module.execute(CONFIG, 'light-request', runner)
    assert not any('KEYCODE_BACK' in c for c in runner.calls)
    assert runner.tap_count == 0


def test_sticky_shade_is_not_repeatedly_dismissed(monkeypatch):
    module = load()
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)
    runner = DisplaysCommands(focus='NotificationShade', sticky=True)
    with pytest.raises(module.ScreenError):
        module.execute(CONFIG, 'light-request', runner)
    assert sum('KEYCODE_BACK' in c for c in runner.calls) == 1
    assert runner.tap_count == 0


@pytest.mark.parametrize('bad', ['missing-app', 'duplicate-app', 'duplicate-current'])
def test_ambiguous_android15_focus_schema_never_closed_or_tapped(bad):
    module = load()
    runner = DisplaysCommands(focus='NotificationShade')
    def ambiguous(args, **kwargs):
        result = runner(args, **kwargs)
        if args[3:] == ['shell', 'dumpsys', 'window', 'displays']:
            lines = result.stdout.splitlines()
            if bad == 'missing-app': lines = lines[:1]
            if bad == 'duplicate-app': lines.append(lines[1])
            if bad == 'duplicate-current': lines.append(lines[0])
            return subprocess.CompletedProcess(args, 0, '\n'.join(lines), '')
        return result
    with pytest.raises(module.ScreenError):
        module.execute(CONFIG, 'light-request', ambiguous)
    assert not any('KEYCODE_BACK' in c for c in runner.calls)
    assert runner.tap_count == 0


def test_keyguard_reappearing_before_shade_close_is_refused():
    module = load()
    runner = DisplaysCommands(focus='NotificationShade')
    policy_reads = 0
    def relocked(args, **kwargs):
        nonlocal policy_reads
        if args[3:] == ['shell', 'dumpsys', 'window', 'policy']:
            policy_reads += 1
            if policy_reads == 3: runner.showing = True
        return runner(args, **kwargs)
    with pytest.raises(module.ScreenError):
        module.execute(CONFIG, 'light-request', relocked)
    assert not any('KEYCODE_BACK' in c for c in runner.calls)
    assert runner.tap_count == 0


class DelayedKeyguardCommands(DisplaysCommands):
    def __init__(self, persistent=False, becomes_secure=False):
        super().__init__()
        self.policy_reads = 0
        self.persistent = persistent
        self.becomes_secure = becomes_secure

    def __call__(self, args, **kwargs):
        if args[3:] == ['shell', 'dumpsys', 'window', 'policy']:
            self.policy_reads += 1
            self.showing = self.persistent or self.policy_reads < 4
            self.secure = self.becomes_secure and self.policy_reads >= 2
        return super().__call__(args, **kwargs)


def test_nonsecure_dismiss_callback_can_finish_after_two_pending_reads(monkeypatch):
    module = load()
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)
    runner = DelayedKeyguardCommands()
    assert module.execute(CONFIG, 'light-request', runner)['light_requested'] is True
    assert sum('dismiss-keyguard' in c for c in runner.calls) == 1
    assert runner.tap_count == 1


def test_persistent_nonsecure_keyguard_waits_bounded_without_redismiss(monkeypatch):
    module = load()
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)
    runner = DelayedKeyguardCommands(persistent=True)
    with pytest.raises(module.ScreenError):
        module.execute(CONFIG, 'light-request', runner)
    assert 7 <= runner.policy_reads <= 11
    assert sum('dismiss-keyguard' in c for c in runner.calls) == 1
    assert not any('KEYCODE_BACK' in c for c in runner.calls)
    assert runner.tap_count == 0


def test_keyguard_becoming_secure_during_wait_refused_immediately(monkeypatch):
    module = load()
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)
    runner = DelayedKeyguardCommands(persistent=True, becomes_secure=True)
    with pytest.raises(module.ScreenError):
        module.execute(CONFIG, 'light-request', runner)
    assert runner.policy_reads == 2
    assert sum('dismiss-keyguard' in c for c in runner.calls) == 1
    assert not any('KEYCODE_BACK' in c for c in runner.calls)
    assert runner.tap_count == 0


def test_keyguard_schema_becoming_unknown_during_wait_is_refused():
    module = load()
    runner = DelayedKeyguardCommands(persistent=True)
    def unknown(args, **kwargs):
        result = runner(args, **kwargs)
        if args[3:] == ['shell', 'dumpsys', 'window', 'policy'] and runner.policy_reads == 2:
            return subprocess.CompletedProcess(args, 0, 'KeyguardServiceDelegate\n  showing=true\n', '')
        return result
    with pytest.raises(module.ScreenError):
        module.execute(CONFIG, 'light-request', unknown)
    assert runner.policy_reads == 2
    assert runner.tap_count == 0
    assert not any('KEYCODE_BACK' in c for c in runner.calls)


def test_keyguard_poll_read_and_sleep_share_two_second_budget(monkeypatch):
    module = load()
    clock = [0.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(module.time, 'sleep', lambda duration: clock.__setitem__(0, clock[0] + duration))
    runner = DelayedKeyguardCommands(persistent=True)
    timeouts = []
    def slow(args, **kwargs):
        timeouts.append(kwargs['timeout'])
        clock[0] += min(0.3, kwargs['timeout'])
        return runner(args, **kwargs)
    with pytest.raises(module.ScreenError):
        module.wait_keyguard_dismissed([CONFIG['adb_path'], '-s', 'phone', 'shell'], slow)
    assert clock[0] <= 2.0
    assert 0 < len(timeouts) < 10
    assert all(0 < value <= 2 for value in timeouts)
    assert timeouts[-1] < timeouts[0]


def test_visible_light_label_tapped_when_clickable_parent_is_partially_clipped():
    label = ui().split('text="')[1].split('"', 1)[0]
    runner = LightCommands(xml=(
        f'<hierarchy><node package="{PACKAGE}" clickable="true" enabled="true" bounds="[0,2100][1080,2900]">'
        f'<node package="{PACKAGE}" text="{label}" clickable="false" enabled="true" bounds="[20,2200][300,2280]"/>'
        '</node></hierarchy>'))
    assert load().execute(CONFIG, 'light-request', runner)['light_requested'] is True
    tap = next(c for c in runner.calls if c[3:6] == ['shell', 'input', 'tap'])
    assert tap[6:] == ['160', '2240']


def test_visible_label_outside_clickable_ancestor_refused():
    module = load()
    label = ui().split('text="')[1].split('"', 1)[0]
    runner = LightCommands(xml=(
        f'<hierarchy><node package="{PACKAGE}" clickable="true" enabled="true" bounds="[400,2100][1000,2300]">'
        f'<node package="{PACKAGE}" text="{label}" clickable="false" enabled="true" bounds="[20,2200][300,2280]"/>'
        '</node></hierarchy>'))
    with pytest.raises(module.ScreenError):
        module.execute(CONFIG, 'light-request', runner)
    assert runner.tap_count == 0
