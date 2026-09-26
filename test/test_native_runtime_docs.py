"""D-161 / D-197 / D-246: the robot runs natively; Docker is dev/CI only.

A reader who opens only README, the Pi runtime runbook or the deployment notes
must come away with one answer to "does our robot run Docker?": no — the product
runtime is native systemd, Docker is development/CI, and the only container lane
is a profile-declared sidecar outside the safety plan. The decision was already
in the ADRs (D-161, D-197, D-198); the operator-facing documents used to still
read like the container era, so the wording itself is pinned here.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

README = ROOT / "README.md"
RUNTIME_GUIDE = ROOT / "docs" / "deployment" / "raspberry-pi-runtime.md"
DEPLOYMENT_AGENTS = ROOT / "docs" / "deployment" / "AGENTS.md"
ARCH = ROOT / "docs" / "architecture" / "15_ROSY_Ubuntu_Modular_Installation.md"
ADR = ROOT / "docs" / "reference" / "ROSY ADR Log.md"
D246 = ROOT / "docs" / "adr" / "D-246-runtime-flexibility-native-default-container-sidecar-lane.md"

# Four conditions a container sidecar has to satisfy (D-246 Decision 4), as the
# architecture document states them in English.
SIDECAR_CONDITIONS = (
    "rosy-runtime.target",
    "cmd_vel",
    "container runtime absent",
    "product release payload",
)

# The same four conditions in the ADR body, where they are written in Korean.
D246_CONDITIONS = (
    "`rosy-runtime.target`의 부팅 경로에 없고",
    "최종 `cmd_vel`를 소유하지 않는다",
    "설치되지 않은 상태에서 항상 통과할 수 있어야 한다",
    "제품 릴리스 payload의 필수 항목이 되지 않는다",
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_readme_says_the_robot_runs_natively_not_docker():
    readme = _text(README)

    assert "**로봇은 네이티브로 돈다.**" in readme
    assert "Docker가 아니라 Ubuntu Server 24.04" in readme
    assert "Docker/Compose는 개발·CI" in readme
    # One robot is never switched between two runtime mechanisms.
    assert "장치마다 컨테이너를 켜고 끄는 옵션은" in readme


def test_runtime_guide_declares_the_native_product_runtime_first():
    guide = _text(RUNTIME_GUIDE)

    assert "Runtime model — native, not Docker (D-161, D-197, D-246)." in guide
    assert "are development/CI tooling only" in guide
    assert "not installed in the product image" in guide
    # The declaration has to precede the first Docker command in the document.
    assert guide.index("Runtime model — native, not Docker") < guide.index("docker compose")


def test_runtime_guide_labels_the_compose_section_as_development():
    guide = _text(RUNTIME_GUIDE)

    assert "## 4. Build and start (development/CI Compose path)" in guide
    assert "On a product robot the equivalent is" in guide
    assert "`systemctl start rosy-runtime.target` with `deploy/robot/native/` units" in guide


def test_deployment_notes_split_product_from_development_dependencies():
    notes = _text(DEPLOYMENT_AGENTS)

    assert "**Runtime model:** the product robot runs **natively**" in notes
    assert "Docker is development/CI tooling only" in notes
    assert "a container sidecar is allowed only for a declared workload outside the" in notes
    assert "- Product: Ubuntu Server 24.04 arm64, native ROS 2 Jazzy, systemd." in notes
    assert "- Development/CI only: Raspberry Pi OS Lite 64-bit, Docker Compose, nmcli." in notes
    # No unqualified "Docker" left in the external dependency list.
    assert "\n- Raspberry Pi OS Lite 64-bit, Docker, nmcli" not in notes


def test_architecture_15_no_longer_says_docker_is_optional():
    arch = _text(ARCH)

    assert "Docker optional" not in arch, (
        "'Docker optional' reads as 'a product robot may run Docker'; D-246 replaced it"
    )
    assert "### Runtime model: native by default (D-161 / D-197 / D-246)" in arch
    assert "The product runtime is native systemd. This is not a per-device choice." in arch
    assert "runs natively on every device, always." in arch
    assert "Container runtime only where a declared profile asks for it (D-246)" in arch
    assert "not installed by default" in arch


def test_architecture_15_states_every_sidecar_condition():
    arch = _text(ARCH)

    for condition in SIDECAR_CONDITIONS:
        assert condition in arch, f"missing sidecar condition: {condition}"


def test_adr_index_records_d246_and_its_qualification_of_d161_and_d197():
    index = _text(ADR)

    d246_row = next(
        (line for line in index.splitlines() if line.startswith("| D-246 |")), None
    )
    assert d246_row is not None, "D-246 is missing from the ADR index"
    assert d246_row.endswith("Accepted |"), d246_row

    d161_row = next(line for line in index.splitlines() if line.startswith("| D-161 |"))
    d197_row = next(line for line in index.splitlines() if line.startswith("| D-197 |"))

    assert "D-246" in d161_row, "D-161's container scope must point at the qualifier"
    assert "D-246" in d197_row, "D-197's sidecar exception must be recorded on its own row"


def test_d246_body_is_complete_and_pins_the_rule():
    body = _text(D246)

    for heading in ("**Status:** Accepted", "**Context:**", "**Decision:**", "**Consequences:**"):
        assert heading in body, f"D-246 is missing {heading}"

    assert "컨테이너 런타임의 기본값은 미설치다" in body
    assert "같은 로봇의 런타임을 Docker와 네이티브로 갈라타는" in body
    for condition in D246_CONDITIONS:
        assert condition in body, f"D-246 body is missing: {condition}"
    assert "test/test_native_runtime_docs.py" in body
