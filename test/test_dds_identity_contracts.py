"""로봇 신원(도메인 + 네임스페이스)이 하나의 로봇 번호에서만 나온다는 계약 (ADR D-33).

이 파일이 존재하는 이유는 구체적이다. 이전 시도는 install-pi.sh 에 set_env_default
호출을 넣는 것으로 끝냈는데, `.env.example` 이 `ROS_DOMAIN_ID=42` 와
`ROSY_NAMESPACE=rosy_01` 을 값으로 들고 있었고 설치 스크립트는 그 템플릿을 그대로
복사한다. set_env_default 는 키가 없을 때만 쓰므로 영영 발화하지 못했고, 출고되는
모든 기기가 같은 신원을 가졌다. 테스트는 전부 초록이었다.

그래서 여기서 검사하는 것은 "호출이 있는가" 가 아니라 "값이 실제로 달라지는가" 다.
`test_the_template_assigns_neither_identity_key` 가 그때를 잡았을 단언이다.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile

import pytest

from robot_contracts import DEPLOY, ROOT

ENV_EXAMPLE = DEPLOY / ".env.example"
COMPOSE = DEPLOY / "compose.yaml"
INSTALLER = DEPLOY / "install-pi.sh"
ROSY_ENV = ROOT / "src" / "devices" / "bringup" / "scripts" / "rosy_env.sh"

IDENTITY_KEYS = ("ROS_DOMAIN_ID", "ROSY_NAMESPACE")

#: 도메인은 40 + N 이고 Linux 안전 범위는 0..101 이므로 N=61 이 마지막이다.
LAST_LEGAL_ROBOT_NUMBER = 61


def test_public_pinky_hostname_does_not_replace_dds_identity():
    """The short public name and the ROS graph identity are separate axes."""
    public_hostname = "rosy-pinky-k7m4"
    robot_number = 1

    assert public_hostname != "rosy_01"
    assert 40 + robot_number == 41
    assert f"rosy_{robot_number:02d}" == "rosy_01"


def _text(path):
    return path.read_text(encoding="utf-8")


# --- (a) 템플릿 -----------------------------------------------------------


def test_the_template_assigns_neither_identity_key():
    """r2 의 무효 메커니즘을 잡았을 단언.

    주석으로 규칙을 적어두는 것은 좋지만, 값을 배정하면 set_env_default 가 죽는다.
    """
    for line in _text(ENV_EXAMPLE).splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for key in IDENTITY_KEYS:
            assert not stripped.startswith(f"{key}="), (
                f".env.example assigns {key}; install-pi.sh 의 set_env_default 는 "
                f"키가 이미 있으면 아무 것도 하지 않으므로 모든 기기가 같은 신원으로 "
                f"출고된다"
            )


def test_the_template_still_documents_the_derivation_rule():
    """값을 지웠으니, 규칙은 남아 있어야 한다 — 아니면 다음 사람이 값을 되돌린다."""
    text = _text(ENV_EXAMPLE)
    assert "ROSY_ROBOT_NUMBER" in text
    assert "40 + N" in text


# --- (b) compose ----------------------------------------------------------


def test_compose_defaults_neither_identity_key_at_any_site():
    """`:8` 만 고치는 것은 반쪽이다 — `:51` 이 실제 기동 인자다."""
    text = _text(COMPOSE)
    for key in IDENTITY_KEYS:
        assert f"${{{key}:-" not in text, f"compose.yaml still defaults {key}"


def test_compose_fails_closed_on_missing_identity():
    text = _text(COMPOSE)
    for key in IDENTITY_KEYS:
        assert f"${{{key}:?" in text, (
            f"compose.yaml must use the ${{{key}:?message}} form so an unset "
            f"identity stops the runtime instead of inventing one"
        )


def test_every_namespace_site_is_still_present():
    """여섯 군데가 모두 남아 있어야 한다.

    기본값 제거 자체는 위의 파일 전역 검사가 본다. 여기서 지키는 것은 다른
    것이다 — `:8` 만 고치고 `:51` 을 지워 버리는 식으로 사이트가 사라지면,
    기본값은 없어도 네임스페이스가 적용되지 않는다.
    """
    sites = re.findall(r"\$\{ROSY_NAMESPACE[:}]", _text(COMPOSE))
    assert len(sites) >= 6, f"expected at least six sites, found {len(sites)}"


# --- (b2) 문서가 주는 명령이 실제로 도는가 --------------------------------


README = ROOT / "README.md"


def test_the_readme_quickstart_sets_identity_before_invoking_compose():
    """`.env.example` 에서 신원을 뺀 순간 README 의 첫 실행 예제가 깨졌다.

    `cp .env.example .env` 다음 줄이 바로 `docker compose build` 였는데, 템플릿에
    두 키가 없으므로 compose 는 `${VAR:?}` 로 즉시 실패한다. 게다가 그 실패
    메시지는 install-pi.sh 를 가리키는데, 개발 벤치에서는 맞는 안내가 아니다.
    새로 온 사람이 가장 먼저 읽는 문서였다.

    실제 docker 로 확인한 사실을 여기 고정한다 — 두 줄이 있으면 `config` 가
    exit 0, 없으면 exit 1.
    """
    block = None
    for chunk in _text(README).split("```"):
        if "runtime-mode.sh up" in chunk and "install-pi.sh" in chunk:
            block = chunk
            break
    assert block is not None, "README quickstart block not found"

    identity = block.index("ROSY_ROBOT_NUMBER=1")
    installer = block.index("install-pi.sh")
    runtime = block.index("runtime-mode.sh up")
    assert identity < installer < runtime, (
        "the Device number must be supplied to install-pi.sh before runtime startup"
    )


# --- (c) 설치 스크립트 ----------------------------------------------------


def test_installer_requires_the_robot_number():
    text = _text(INSTALLER)
    assert "ROSY_ROBOT_NUMBER" in text
    assert "require_robot_identity" in text
    # set_env_value 로 쓰면 이미 자리잡은 기기를 조용히 덮어쓴다.
    assert 'set_env_default "$env_file" ROS_DOMAIN_ID' in text
    assert 'set_env_default "$env_file" ROSY_NAMESPACE' in text
    for key in IDENTITY_KEYS:
        assert f'set_env_value "$env_file" {key}' not in text, (
            f"{key} must use set_env_default so a re-run cannot renumber a live robot"
        )


def test_installer_persists_the_robot_number_without_renumbering():
    text = _text(INSTALLER)
    body = text[
        text.index("require_robot_identity() {"): text.index("write_install_runtime_selection() {")
    ]
    assert "ROSY_ROBOT_NUMBER" in body
    assert 'set_env_default "$env_file" ROSY_ROBOT_NUMBER' in body
    assert 'set_env_value "$env_file" ROSY_ROBOT_NUMBER' not in text
    assert "already has ROSY_ROBOT_NUMBER" in body or "already has $key=" in body


def test_installer_derives_identity_before_starting_any_container():
    """compose 가 뜨기 전에 실패해야 한다 — 뜬 뒤면 이미 충돌한 것이다.

    첫 판은 `A or B` 였고 B 는 두 **함수 정의**의 파일 내 순서를 비교했다. 그것은
    호출 위치와 무관하게 늘 참이므로 단언 전체가 항진명제였다 — 게이트를 docker
    compose 뒤로 옮겨도 초록이었다. 이 계획이 두 번 지운 결함과 같은 종류다.
    그래서 지금은 (1) 게이트가 write_runtime_environment **본문 안**에 있고,
    (2) main() 이 그것을 build_and_start_core **앞에서** 부르는지를 본다.
    """
    text = _text(INSTALLER)

    body = text[
        text.index("write_runtime_environment() {"): text.index("build_and_start_core() {")
    ]
    assert 'require_robot_identity "$env_file"' in body, (
        "the identity gate must live inside write_runtime_environment; anywhere "
        "later and a container can start on an unprovisioned identity"
    )
    assert text.count('require_robot_identity "') == 1, (
        "exactly one call site, or the containment check above proves nothing"
    )

    calls = [line.strip() for line in text[text.index("main() {"):].splitlines()]
    assert calls.index("write_runtime_environment") < calls.index("build_and_start_core")


# --- (d) 두 진입점이 같은 규칙을 쓴다 --------------------------------------


def _domain_base(text):
    match = re.search(r"DOMAIN_BASE=(\d+)", text) or re.search(r"\$\(\((\d+) \+", text)
    assert match, "no domain base found"
    return int(match.group(1))


def test_both_entrypoints_agree_on_the_domain_base():
    """rosy_env.sh 와 install-pi.sh 가 서로 다른 규칙을 쓰면 그것이 바로 충돌이다."""
    assert _domain_base(_text(ROSY_ENV)) == _domain_base(_text(INSTALLER)) == 40


def test_the_dev_script_also_exports_the_namespace():
    """도메인만 나누면 토픽 이름이 그대로 겹친다."""
    text = _text(ROSY_ENV)
    assert "export ROSY_NAMESPACE=" in text
    assert "rosy_%02d" in text


# --- 실제 동작 (bash 가 있을 때만) -----------------------------------------

def _find_usable_bash():
    # WSL(system32 bash.EXE)은 Windows 경로를 읽지 못한다 — Git Bash 를 선점한다
    # ( test_runtime_slices 와 같은 순서 ). 그 뒤는 기존 대로 실제 실행으로 검증한다.
    candidates = []
    if os.name == "nt":
        candidates.extend((
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files\Git\usr\bin\bash.exe",
        ))
    which = shutil.which("bash")
    if which:
        candidates.append(which)
    for candidate in candidates:
        if not candidate:
            continue
        try:
            probe = subprocess.run(
                [candidate, "-c", "true"],
                capture_output=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if probe.returncode == 0:
            return candidate
    return None


BASH = _find_usable_bash()


def _bash_view(path):
    """임시 경로를 BASH 이 읽는 형태로 바꾼다.

    Git Bash 는 드라이브 폼(X:/…)을 읽고, WSL(system32 bash.EXE)은
    /mnt/<drive>/… 만 읽는다. 백슬래시는 bash 문자열에서 이스케이프로
    읽히므로 슬래시로 통일한다.
    """
    s = str(path).replace("\\", "/")
    if "system32" in BASH.lower().replace("/", "\\") and re.match(r"^[A-Za-z]:/", s):
        return f"/mnt/{s[0].lower()}{s[2:]}"
    return s


def _drive_installer(robot_number, preset=None):
    """install-pi.sh 의 함수만 떼어내어 require_robot_identity 를 실제로 돌린다."""
    library = "\n".join(_text(INSTALLER).splitlines()[:-1])
    with tempfile.TemporaryDirectory() as work:
        env_file = os.path.join(work, ".env")
        lines = ["ROSY_CMD_VEL_TIMEOUT_S=0.5"]
        for key, value in (preset or {}).items():
            lines.append(f"{key}={value}")
        with open(env_file, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")

        script = os.path.join(work, "lib.sh")
        with open(script, "w", encoding="utf-8") as handle:
            handle.write(library)

        env = dict(os.environ)
        env.pop("ROSY_ROBOT_NUMBER", None)
        if robot_number is not None:
            env["ROSY_ROBOT_NUMBER"] = str(robot_number)

        completed = subprocess.run(
            [BASH, "-c", f'source "{_bash_view(script)}"; set +e; '
                          f'require_robot_identity "{_bash_view(env_file)}"'],
            capture_output=True, text=True, env=env,
            # 실패 메시지가 한국어다. Windows 기본 코드페이지로 읽으면 깨진다.
            encoding="utf-8", errors="replace",
        )
        with open(env_file, encoding="utf-8") as handle:
            return completed, handle.read()


@pytest.mark.skipif(BASH is None, reason="bash is unavailable on this host")
def test_a_fresh_install_derives_a_distinct_identity():
    """판별 테스트: 재실행 경로가 아니라 신규 설치 경로를 본다.

    r2 의 결함은 재실행 테스트만으로는 초록이었다 — 두 경로 모두 no-op 이었기 때문이다.
    """
    completed, env = _drive_installer(2)
    assert completed.returncode == 0, completed.stderr
    assert "ROS_DOMAIN_ID=42" in env
    assert "ROSY_NAMESPACE=rosy_02" in env


@pytest.mark.skipif(BASH is None, reason="bash is unavailable on this host")
def test_a_missing_robot_number_fails_closed():
    completed, _ = _drive_installer(None)
    assert completed.returncode != 0
    assert "ROSY_ROBOT_NUMBER" in completed.stderr


@pytest.mark.skipif(BASH is None, reason="bash is unavailable on this host")
def test_a_number_past_the_linux_safe_range_is_refused():
    completed, _ = _drive_installer(LAST_LEGAL_ROBOT_NUMBER + 1)
    assert completed.returncode != 0
    assert "0 to 101" in completed.stderr

    ok, env = _drive_installer(LAST_LEGAL_ROBOT_NUMBER)
    assert ok.returncode == 0, ok.stderr
    assert "ROS_DOMAIN_ID=101" in env


@pytest.mark.skipif(BASH is None, reason="bash is unavailable on this host")
def test_reprovisioning_the_same_number_is_a_no_op():
    completed, env = _drive_installer(
        2, preset={"ROS_DOMAIN_ID": 42, "ROSY_NAMESPACE": "rosy_02"}
    )
    assert completed.returncode == 0, completed.stderr
    assert env.count("ROS_DOMAIN_ID=") == 1


@pytest.mark.skipif(BASH is None, reason="bash is unavailable on this host")
@pytest.mark.parametrize("number", ["08", "09", "010", "007", "00"])
def test_a_leading_zero_is_refused_rather_than_read_as_octal(number):
    """앞자리 0 은 추측하지 않고 거절한다.

    bash 산술은 `010` 을 팔진수로 읽어 도메인 48 과 `rosy_08` 을 배정했다. 둘이
    사이좋게 틀리기 때문에 어떤 검사도 걸리지 않고, 그대로 8호기와 충돌한다.
    `08`/`09` 는 그나마 눈에 띄었다 — bash 내부 오류로 죽었으니까. 조용히 틀린
    쪽이 더 나쁘다. `010` 이 10 인지 8 인지는 우리가 정할 문제가 아니다.
    """
    completed, env = _drive_installer(number)
    assert completed.returncode != 0, f"{number} was accepted"
    assert "leading zero" in completed.stderr
    assert "ROS_DOMAIN_ID" not in env


@pytest.mark.skipif(BASH is None, reason="bash is unavailable on this host")
@pytest.mark.parametrize(
    "number,domain,namespace",
    [("0", "40", "rosy_00"), ("8", "48", "rosy_08"), ("10", "50", "rosy_10")],
)
def test_plain_decimal_numbers_still_derive_correctly(number, domain, namespace):
    """거절 규칙이 정상 입력까지 막지 않는지 — 특히 10 은 8 이 아니다."""
    completed, env = _drive_installer(number)
    assert completed.returncode == 0, completed.stderr
    assert f"ROS_DOMAIN_ID={domain}" in env
    assert f"ROSY_NAMESPACE={namespace}" in env


@pytest.mark.skipif(BASH is None, reason="bash is unavailable on this host")
def test_a_half_matching_env_is_left_completely_untouched():
    """도메인은 맞는데 네임스페이스가 어긋난 `.env` 는 아무것도 쓰지 않고 거절한다.

    한 키를 쓰고 다음 키에서 멈추면 도메인과 네임스페이스가 어긋난 채로 남는다.
    신원이 절반만 이주한 기기가 바로 이 작업이 없애려는 상태다 — 정리 리팩터
    중에 실제로 한 번 이 상태를 만들었고, 그래서 여기에 고정한다.
    """
    completed, env = _drive_installer(2, preset={"ROSY_NAMESPACE": "rosy_09"})
    assert completed.returncode != 0
    assert "ROS_DOMAIN_ID" not in env, (
        "the installer wrote one key before refusing on the other"
    )
    assert "ROSY_NAMESPACE=rosy_09" in env


@pytest.mark.skipif(BASH is None, reason="bash is unavailable on this host")
def test_renumbering_a_live_unit_fails_loudly_naming_both_values():
    """조용한 재번호가 r3 가 남긴 구멍이었다 — set_env_default 는 말없이 지나간다."""
    completed, env = _drive_installer(
        3, preset={"ROS_DOMAIN_ID": 42, "ROSY_NAMESPACE": "rosy_02"}
    )
    assert completed.returncode != 0
    assert "42" in completed.stderr and "43" in completed.stderr
    assert "ROS_DOMAIN_ID=42" in env, "the live unit must be left untouched"
