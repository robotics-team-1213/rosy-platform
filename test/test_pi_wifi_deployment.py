"""Static safety contracts for headless Raspberry Pi Wi-Fi deployment."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "robot"
INSTALLER = DEPLOY / "install-pi.sh"
VERIFY = DEPLOY / "verify"
VERIFIER = VERIFY / "verify-pi.sh"
READBACK = VERIFY / "device-readback.sh"
READBACK_PY = VERIFY / "device_readback.py"
RUNTIME_MODE = DEPLOY / "runtime-mode.sh"
WINDOWS_DEPLOY = DEPLOY / "deploy-from-windows.ps1"
WINDOWS_VERIFY = VERIFY / "verify-from-windows.ps1"
UART_CONFIG = DEPLOY / "configure-uart-pi5.sh"
MOTOR_VERIFY = VERIFY / "verify-motors.sh"
RESOLVE_MODE = DEPLOY / "config" / "resolve-mode.sh"

def _find_usable_bash():
    candidate = shutil.which("bash")
    if not candidate:
        return None
    try:
        probe = subprocess.run(
            [candidate, "-c", "true"],
            capture_output=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return candidate if probe.returncode == 0 else None


BASH = _find_usable_bash()
bash_only = pytest.mark.skipif(
    BASH is None,
    reason="bash is required to exercise the runtime-mode resolver",
)




def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_deployment_kit_files_exist():
    for path in (
        INSTALLER,
        VERIFIER,
        READBACK,
        READBACK_PY,
        RUNTIME_MODE,
        WINDOWS_DEPLOY,
        WINDOWS_VERIFY,
        UART_CONFIG,
        MOTOR_VERIFY,
    ):
        assert path.is_file(), f"missing deployment file: {path.relative_to(ROOT)}"


def test_installer_uses_official_arm64_capable_docker_repository():
    script = _text(INSTALLER)

    assert "download.docker.com/linux/debian" in script
    assert "docker-ce" in script
    assert "docker-buildx-plugin" in script
    assert "docker-compose-plugin" in script
    assert "get.docker.com" not in script
    assert "/proc/device-tree/model" in script
    assert "aarch64" in script
    assert "VERSION_CODENAME" in script


def test_installer_generates_device_local_tokens_and_preserves_config():
    script = _text(INSTALLER)

    assert "openssl rand -hex" in script
    assert "initial-credentials" in script
    assert "chmod 0600" in script
    assert "-m 0640" in script
    assert 'if [[ ! -f "$ROSY_CONFIG" ]]' in script
    assert "rosy-dev-admin" not in script
    assert "WIFI_PASSWORD" not in script
    assert "SSID=" not in script
    assert "set_env_default" in script
    assert "set_env_default \"$env_file\" ROSY_MOTOR_BAUDRATE 1000000" in script
    assert "set_env_default \"$env_file\" ROSY_MOTOR_IDS '[1,2]'" in script
    assert "set_env_default \"$env_file\" ROSY_MAX_LINEAR_MPS 0.20" in script
    assert "set_env_default \"$env_file\" ROSY_MAX_ANGULAR_RPS 0.80" in script
    assert "set_env_default \"$env_file\" ROSY_MAX_WHEEL_RPM 100.0" in script
    assert (
        "set_env_default \"$env_file\" ROSY_MOTOR_PROFILE_ACCELERATION 200"
        in script
    )


def test_installer_guards_destructive_paths_and_activates_systemd():
    script = _text(INSTALLER)

    assert '[[ "$INSTALL_ROOT" == "/opt/rosy" ]]' in script
    assert '[[ "$ROSY_CONFIG" == "/etc/rosy/rosy.yaml" ]]' in script
    assert '[[ "$ROSY_DATA" == "/var/lib/rosy" ]]' in script
    assert "umask 077" in script
    assert '[[ ! -L "$INSTALL_ROOT" ]]' in script
    assert '[[ "$install_real" == "$INSTALL_ROOT" ]]' in script
    assert '[[ "$source_real" != "$INSTALL_ROOT/"* ]]' in script
    assert "--chown=root:root" in script
    assert "--exclude 'deploy/robot/.env'" in script
    assert "systemctl stop rosy-runtime.service" in script
    assert "trap on_install_exit EXIT" in script
    assert "systemctl disable --now rosy-runtime.service" in script
    assert "Rosy remains quarantined in core-off state" in script
    assert "systemctl enable --now rosy-runtime.service" in script
    assert 'grep -Eq "CHANGE_ME|rosy-dev-" "$ROSY_CONFIG"' in script
    assert 'chown root:"$run_group" "$ROSY_CONFIG"' in script
    assert 'chmod 0640 "$ROSY_CONFIG"' in script
    assert 'chown root:"$run_group" "$env_file"' in script
    assert 'chmod 0640 "$env_file"' in script
    assert "preflight_host\n    stop_existing_runtime\n    install_host_packages" in script


def test_installer_uses_private_temporary_docker_key_file():
    script = _text(INSTALLER)

    assert "mktemp" in script
    assert "/tmp/rosy-docker.asc" not in script


def test_runtime_defaults_to_core_and_the_unit_drives_the_wrapper():
    environment = _text(DEPLOY / ".env.example")
    wrapper = _text(RUNTIME_MODE)
    unit = _text(DEPLOY / "rosy-runtime.service")

    assert "ROSY_RUNTIME_MODE=core" in environment
    assert '${ROSY_RUNTIME_MODE:-core}' in wrapper
    assert "s/^ROSY_RUNTIME_MODE=//p" in wrapper
    assert '--profile motor up -d --remove-orphans rosy-core rosy-motor' in wrapper
    assert "runtime-mode.sh up" in unit
    assert "runtime-mode.sh down" in unit
    assert "network-online.target" in unit
    assert "docker.service" in unit


def _resolve(mode: str) -> subprocess.CompletedProcess:
    """Run the real resolver against the real board catalog.

    Mode validation used to sit inline in runtime-mode.sh and this test read it
    out of that file. It moved to config/resolve-mode.sh, and the grep kept
    passing until it did not — a test that greps for a case statement is
    asserting where the code lives, not what it does.
    """
    # Run from the config directory with relative names: a Windows drive path
    # is not something Git Bash can `source`, and this is also how the wrapper
    # uses it — beside its own board.yaml.
    return subprocess.run(
        [BASH, "-c",
         f'source ./resolve-mode.sh; resolve_runtime_mode "{mode}" ./board.yaml'],
        cwd=str(RESOLVE_MODE.parent), capture_output=True, text=True,
        # text=True decodes with the locale codec, which is cp949 here and
        # chokes on a non-ASCII byte in a subprocess's own error output.
        encoding="utf-8", errors="replace", check=False,
    )


@bash_only
@pytest.mark.parametrize("mode", ["core", "motor", "hardware"])
def test_a_catalog_mode_resolves_to_itself(mode):
    result = _resolve(mode)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == mode


def _catalog_aliases() -> dict:
    board = yaml.safe_load(_text(DEPLOY / "config" / "board.yaml"))
    return board.get("aliases") or {}


@bash_only
def test_every_alias_in_the_catalog_resolves_to_its_mode():
    """Reading the catalog rather than naming one alias.

    The resolver holds a second definition of a valid alias name (the
    identifier regex that keeps punctuation out of the sed lookup). Nothing
    keeps the two in step, so the test iterates what the catalog actually
    declares — adding an alias the regex rejects must fail here.
    """
    aliases = _catalog_aliases()
    assert aliases, "the catalog declares no aliases; this test proves nothing"

    for alias, mode in aliases.items():
        result = _resolve(str(alias))
        assert result.returncode == 0, f"{alias}: {result.stderr}"
        assert result.stdout.strip() == str(mode)


@bash_only
@pytest.mark.parametrize("mode", ["hardwear", "HARDWARE", "core motor", "../hardware", ""])
def test_an_unknown_mode_is_refused_rather_than_guessed(mode):
    """Guessing here would boot a slice the operator did not ask for."""
    result = _resolve(mode)

    assert result.returncode != 0, f"{mode!r} resolved to {result.stdout.strip()!r}"
    assert result.stdout.strip() == ""
    assert result.stderr.strip(), "a refusal the operator cannot read is not a refusal"


@bash_only
@pytest.mark.parametrize("mode", ["../hardware", "core;rm", "hard ware"])
def test_a_malformed_mode_is_answered_by_the_resolver_not_by_sed(mode):
    """The value reaches a sed expression. An operator must read why it was
    refused, not sed's opinion of the punctuation."""
    result = _resolve(mode)

    assert "ROSY_RUNTIME_MODE" in result.stderr
    assert "sed:" not in result.stderr


@bash_only
def test_an_unknown_mode_names_what_it_would_have_accepted():
    result = _resolve("hardwear")

    assert "core" in result.stderr and "motor" in result.stderr
    assert "board.yaml" in result.stderr


def test_network_verifier_supports_auto_wired_or_wifi_lan():
    script = _text(VERIFIER)

    for command in (
        "nmcli radio wifi",
        "nmcli -t -f GENERAL.CONNECTION",
        "ip -4",
        "ip route show default",
        "getent ahosts",
        "curl",
        "/api/v1",
        "/dashboard",
        "--require-internet",
        "--interface",
        'network_interface="auto"',
        "default_interface",
    ):
        assert command in script
    for gate in ("WIFI", "LAN", "DNS", "INTERNET", "RUNTIME", "DASHBOARD"):
        assert gate in script
    assert "WIFI_PASSWORD" not in script
    assert 'ip route show default dev "$network_interface"' in script
    assert 'curl --interface "$network_interface"' in script
    assert 'if [[ "$network_interface" == wlan* ]]' in script
    assert '"$network_interface" == "lo"' in script
    assert 'runtime_service="rosy-motor"' in script
    assert 'runtime_service="rosy-io"' in script
    assert "capabilities.${configured_mode}.yaml" in script
    assert "missing board overlay" in script
    assert "requires running $runtime_service" in script


def test_windows_uploader_archives_only_git_head_and_keeps_ssh_host_checks():
    script = _text(WINDOWS_DEPLOY)

    assert "git archive" in script
    assert "Get-FileHash" in script
    assert "scp" in script
    assert "ssh" in script
    assert "git status --porcelain" in script
    assert "StrictHostKeyChecking=no" not in script
    assert "WifiPassword" not in script
    assert "CHANGE_ME" not in script
    assert "verify-from-windows.ps1" in script


def test_the_windows_deployer_passes_a_robot_number_to_the_installer():
    """이 스크립트는 설치기를 원격에서 부른다. 번호를 넘기지 않으면 항상 실패한다.

    D-33 이후 `install-pi.sh` 는 `ROSY_ROBOT_NUMBER` 없이는 거절한다. 그런데 이
    스크립트는 `sudo bash ... install-pi.sh` 를 그대로 부르고 있었으므로, 문서에
    적힌 Windows→Pi 배포 경로 전체가 깨져 있었다. README 퀵스타트와 같은 부류의
    부수 피해다 — 코드는 맞는데 사람이 따라 할 순서가 끊겼다.

    기본값을 두는 것으로 고치지 않는다. 기본값이 있으면 이 스크립트로 배포한 모든
    기기가 같은 도메인으로 뜨고, 그것이 D-33 이 없앤 결함 그 자체다.
    """
    script = _text(WINDOWS_DEPLOY)

    assert "ROSY_ROBOT_NUMBER=$RobotNumber bash deploy/robot/install-pi.sh" in script, (
        "the installer must receive the robot number, or every deploy fails"
    )
    assert "sudo bash deploy/robot/install-pi.sh" not in script, (
        "the bare invocation cannot provision an identity"
    )
    assert '[string]$RobotNumber = ""' in script, "RobotNumber must be a parameter"
    assert "RobotNumber is required" in script, (
        "an absent number must fail loudly rather than default to one robot"
    )
    # 앞자리 0 은 bash 산술이 팔진수로 읽는다 — 설치기와 같은 규칙을 여기서도 건다.
    assert "no leading zero" in script
    assert "-gt 101" in script, "the Linux-safe domain range must be checked here too"


def test_the_wifi_image_doc_invokes_the_deployer_with_a_robot_number():
    """문서에 적힌 명령이 실제로 도는지 — 이번에도 그게 깨진 부분이었다."""
    doc = _text(ROOT / "docs" / "deployment" / "raspberry-pi-wifi-image.md")

    block = None
    for chunk in doc.split("```"):
        if "deploy-from-windows.ps1" in chunk:
            block = chunk
            break
    assert block is not None, "the documented invocation is missing"
    assert "-RobotNumber" in block, (
        "the documented command omits the robot number and would fail at install"
    )


def test_uart4_configuration_is_explicit_idempotent_and_does_not_move_motors():
    script = _text(UART_CONFIG)

    assert "/boot/firmware/config.txt" in script
    assert "dtoverlay=uart4-pi5" in script
    assert "[all]" in script
    assert "overlay_applies_to_pi5" in script
    assert '"[pi5]"' in script
    assert "grep -Fqx" in script
    assert "mktemp" in script
    assert "goal velocity" not in script.lower()
    assert "torque" not in script.lower()


def test_motor_preflight_checks_uart_and_runs_torque_free_dynamixel_probe():
    script = _text(MOTOR_VERIFY)
    probe = _text(ROOT / "src" / "devices" / "bringup" / "bringup" / "dynamixel_probe.py")

    assert "/proc/device-tree/model" in script
    assert "dtoverlay=uart4-pi5" in script
    assert "overlay_applies_to_pi5" in script
    assert "ttyAMA4" in script
    assert "console=ttyAMA4" in script
    assert "dynamixel_probe" in script
    assert "--profile motor" in script
    assert "build rosy-motor" in script
    assert 'source "$ENV_FILE"' not in script
    assert "ROSY_DIALOUT_GID" in script
    assert "stat -c '%g'" in script
    assert ".ping(" in probe
    assert "ADDR_TORQUE_ENABLE" in probe
    assert "read1ByteTxRx" in probe
    assert "write1ByteTxRx" not in probe
    assert "write4ByteTxRx" not in probe


@bash_only
def test_the_motor_runtime_gate_fails_closed_when_compose_cannot_answer(tmp_path):
    """이 게이트는 살아 있는 모터 런타임 위로 UART 프로브가 겹치는 것을 막는다.

    예전 형태는 compose 의 *출력이 비었는지*만 봤다. 그런데 compose 가 아예
    실패해도 출력은 비므로, 게이트가 조용히 통과하고 프로브가 그대로 진행됐다.
    docker 부재, 잘못된 compose 파일, 그리고 (ADR D-33 이후로는) 신원 미설정이
    모두 그 경로를 탄다.

    소스 텍스트가 아니라 실제 bash 로 확인한다 — 이 결함의 본질이 "코드는
    그럴듯한데 동작이 다르다" 였기 때문이다.
    """
    script = _text(MOTOR_VERIFY)
    assert 'if ! running="$(' in script, (
        "the gate must branch on compose's exit status, not only on empty output"
    )

    stub = tmp_path / "bin"
    stub.mkdir()
    docker = stub / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\necho 'compose exploded' >&2\nexit 1\n", encoding="utf-8"
    )
    docker.chmod(0o755)

    gate = script[script.index('if ! running="$('):script.index('pass "UART4 overlay')]
    harness = tmp_path / "gate.sh"
    harness.write_text(
        "set -Eeuo pipefail\n"
        # 여기 bash 는 Windows 드라이브 경로를 풀지 못한다 — 스텁도 cwd 기준
        # 상대이름으로 올려야 한다 (test_image_pipeline.py 가 같은 교훈을 적어 뒀다).
        'export PATH="./bin:$PATH"\n'
        'fail() { echo "FAIL MOTOR_PREFLIGHT $*" >&2; exit 1; }\n'
        "compose=(docker compose --env-file /dev/null)\n"
        + gate
        + "\necho REACHED_THE_PROBE\n",
        encoding="utf-8",
        newline="\n",
    )

    # 여기 bash 는 Windows 드라이브 경로도 그 MSYS 형태도 풀지 못한다 —
    # test_image_pipeline.py 가 같은 이유로 상대이름 + 명시적 cwd 를 쓴다.
    result = subprocess.run(
        [BASH, "gate.sh"],
        cwd=str(tmp_path),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )

    assert result.returncode != 0, result.stdout
    assert "REACHED_THE_PROBE" not in result.stdout, (
        "the probe ran even though compose could not report the runtime state"
    )
    assert "docker compose failed" in result.stderr


def test_windows_peer_verifier_checks_api_and_dashboard_over_selected_lan():
    script = _text(WINDOWS_VERIFY)

    assert '[string]$NetworkInterface = "auto"' in script
    assert "ip -4 route show default" in script
    assert 'show dev $NetworkInterface scope global' in script
    assert "Invoke-WebRequest" in script
    assert "/api/v1" in script
    assert "/dashboard" in script
    assert "StrictHostKeyChecking=no" not in script
    assert "Authorization" not in script


def test_shell_scripts_are_lf_only():
    for path in (
        INSTALLER,
        VERIFIER,
        RUNTIME_MODE,
        UART_CONFIG,
        MOTOR_VERIFY,
        DEPLOY / "entrypoint.sh",
    ):
        assert b"\r\n" not in path.read_bytes(), f"CRLF is unsafe in container/Pi shell: {path.name}"


def test_pi_profile_binds_dashboard_to_wifi_reachable_interface():
    config = yaml.safe_load(_text(DEPLOY / "config" / "rosy.pi5.example.yaml"))

    assert config["network"]["api_host"] == "0.0.0.0"
    assert config["network"]["api_port"] == 8080


def test_wifi_runbook_is_linked_from_runtime_guide():
    runbook = ROOT / "docs" / "deployment" / "raspberry-pi-wifi-image.md"
    runtime_guide = _text(ROOT / "docs" / "deployment" / "raspberry-pi-runtime.md")
    readme = _text(ROOT / "README.md")

    assert runbook.is_file()
    assert "raspberry-pi-wifi-image.md" in runtime_guide
    assert "raspberry-pi-wifi-image.md" in readme
    assert "sudoedit /opt/rosy/deploy/robot/.env" in runtime_guide
    assert "sudo install -d -o rosy -g rosy /opt/rosy" not in runtime_guide
    assert "cp .env.example .env" not in runtime_guide
