"""패키지 뼈대. fleet 이 import 되고, D-18 대로 core 스키마를 재사용할 수 있다."""

import xml.etree.ElementTree as ET
from pathlib import Path


def test_package_imports_and_reaches_core_schemas():
    import fleet
    from core_common.protocol.schemas import SwarmFollowParams

    # 버전은 package.xml, setup.py, __init__.py 세 곳에 있다. 이 테스트는 __init__.py 를
    # package.xml 과 맞춘다; setup.py 는 여기서 검사하지 않는다.
    manifest = Path(__file__).resolve().parents[1] / "package.xml"
    assert fleet.__version__ == ET.parse(manifest).getroot().findtext("version")
    # 값 자체는 core 의 테스트가 지킨다. 여기서 보는 것은 import 가 닿는다는 것이다.
    assert SwarmFollowParams(target_robot_id="rosy_01").distance == 0.5
