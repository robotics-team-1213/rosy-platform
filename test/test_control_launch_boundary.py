from robot_contracts import DEPLOY, ROOT

#: D-150: web_node debug ports and executable stay inside the control debug surface.
DEBUG_PORT_MARKERS = ("28181", "28182")
DEPLOY_TEXT_SUFFIXES = {".yaml", ".yml", ".service", ".sh", ".ps1", ".py", ".timer", ".path"}


def _deploy_text_files():
    for path in sorted(DEPLOY.rglob("*")):
        if "__pycache__" in path.parts or not path.is_file():
            continue
        if path.suffix in DEPLOY_TEXT_SUFFIXES or path.name == "compose.yaml":
            yield path


def test_operational_compose_does_not_launch_legacy_control_stack():
    text = (DEPLOY / "compose.yaml").read_text(encoding="utf-8")
    assert "runtime/sensing/launch" not in text
    assert "runtime/sensing/launch/robot.launch.py" not in text


def test_operational_compose_does_not_serve_the_control_console():
    """D-77: 운용자 콘솔은 CORE /dashboard. web_node는 compose에 없다."""
    text = (DEPLOY / "compose.yaml").read_text(encoding="utf-8")
    assert "web_node" not in text
    assert "dashboard.html" not in text
    html = (ROOT / "src" / "runtime" / "sensing" / "web" / "dashboard.html").read_text(encoding="utf-8")
    assert "<title>pinky console</title>" not in html
    assert "<title>Rosy control diagnostic</title>" in html


def test_hardware_launch_does_not_start_safety_as_final_publisher():
    nav = ROOT / "src" / "runtime" / "navigation" / "launch" / "hardware.launch.py"
    text = nav.read_text(encoding="utf-8")
    assert "runtime/sensing" not in text
    assert "safety_node" not in text


def test_deploy_configs_do_not_expose_control_debug_surface():
    """D-150: web_node ports/executable never leak into deploy configs or units.

    compose.yaml 은 D-77 검사가 지키고 있다 — 여기는 그 아래 깔리는 모든
    설정/유닛/스크립트까지 확장한다. web_node 는 control 디버그 서피스이며
    운영 구성의 어떤 파일도 그 포트(28181/28182)를 여는 이름을 가져선 안 된다.
    """
    offenders = []
    for path in _deploy_text_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        if "web_node" in text or any(port in text for port in DEBUG_PORT_MARKERS):
            offenders.append(path.relative_to(DEPLOY).as_posix())
    assert not offenders, (
        "control debug surface leaked into deploy config (D-150): " + ", ".join(offenders)
    )


def test_core_launches_do_not_reference_the_control_stack():
    """D-149: CORE launch files stay CORE-only; control nodes never ride along.

    단일 발행자 원칙(D-2/D-38)의 코어 쪽 면 — core launch 가 control 노드를
    포함하면 control 의 standalone 최종 발행(계약된 예외)과 CORE 가 같은
    그래프에서 만난다. launch 파일 이름 개명(rosy_core → core)에도 견디도록
    디렉터리를 glob 한다.
    """
    core_launch_dir = ROOT / "src" / "runtime" / "gateway" / "launch"
    launches = sorted(core_launch_dir.glob("*.launch.py"))
    assert launches, "core launch directory unexpectedly empty — guard lost its scope"
    offenders = []
    for path in launches:
        text = path.read_text(encoding="utf-8")
        for marker in ("package='control'", 'package="control"', "runtime/sensing"):
            if marker in text:
                offenders.append(f"{path.name}: {marker}")
    assert not offenders, (
        "CORE launch must not reference the control stack (D-149): " + ", ".join(offenders)
    )
