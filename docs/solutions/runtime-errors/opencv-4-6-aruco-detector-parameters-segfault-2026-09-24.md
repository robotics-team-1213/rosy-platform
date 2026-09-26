---
title: OpenCV 4.6의 bare aruco.DetectorParameters()는 널 포인터라 필드 하나만 써도 import에서 segfault가 난다
date: 2026-09-24
category: runtime-errors
module: core/control (sensing/dock_tag, dock_observer_node)
problem_type: runtime_error
component: development_workflow
severity: high
symptoms:
  - "dock_observer_node가 로그 한 줄 없이 exit -11로 죽음 (Gazebo 미션 세 개 모두)"
  - "Windows 호스트 pytest는 전부 통과"
  - "ROS 장치/WSL 쪽에서만 재현되고, 같은 결함을 main도 따로 만남"
root_cause: wrong_api
resolution_type: code_fix
framework_version: "opencv 4.6.0 (Ubuntu 24.04 apt python3-opencv)"
related_components:
  - testing_framework
tags: [opencv, aruco, segfault, api-version, import-time, host-vs-device, dock-tag]
---

# OpenCV 4.6의 bare aruco.DetectorParameters()는 널 포인터라 필드 하나만 써도 import에서 segfault가 난다

## Problem

Ubuntu 24.04의 apt `python3-opencv`는 4.6이다. 이 버전에서 `cv2.aruco.DetectorParameters()`를
인자 없이 만들면 널 포인터를 감싼 객체가 나오고, 필드 하나(`cornerRefinementMethod`)만 설정해도
인터프리터가 native crash로 죽는다. `src/core/control/control/sensing/dock_tag.py`는 모듈 import
시점에 검출기를 만들기 때문에(`_DETECT_MARKERS = _marker_detector(cv2.aruco)`),
`dock_observer_node`가 로그를 남기기도 전에 exit -11로 죽었다.

## Symptoms

- 노드가 시작 직후 exit -11. Python traceback이 없다.
- Windows 호스트의 OpenCV는 5.0.0이라 호스트 테스트는 모두 초록이었다.

## What Didn't Work

- 호스트 pytest. 호스트 OpenCV에는 4.7 이후 API(`ArucoDetector`, 정상 동작하는
  `DetectorParameters()`)가 있어서 결함 경로를 한 번도 지나지 않는다. in-process import
  테스트로는 segfault를 볼 수도 없다. 테스트 프로세스가 같이 죽거나, 애초에 크래시가 나지 않는다.

## Solution

`dock_tag.py`가 두 API 세대를 모두 지원한다.

```python
def _detector_parameters(aruco):
    create = getattr(aruco, "DetectorParameters_create", None)
    parameters = create() if create is not None else aruco.DetectorParameters()
    parameters.cornerRefinementMethod = aruco.CORNER_REFINE_SUBPIX
    return parameters


def _marker_detector(aruco):
    dictionary = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
    parameters = _detector_parameters(aruco)
    if hasattr(aruco, "ArucoDetector"):
        return aruco.ArucoDetector(dictionary, parameters).detectMarkers
    return lambda gray: aruco.detectMarkers(gray, dictionary, parameters=parameters)
```

- 4.7 이전: 파라미터는 `DetectorParameters_create()`로만 만든다. 검출은 free function
  `aruco.detectMarkers()`로 한다(4.6에는 `ArucoDetector`가 없다).
- 4.7 이후: `DetectorParameters()`와 `ArucoDetector`를 쓴다.

가드 테스트는 `src/core/control/test/test_dock_tag.py`에 있다.

- `test_the_module_imports_in_a_fresh_interpreter` — `python -X faulthandler -c "import
  control.sensing.dock_tag"`를 자식 인터프리터로 돌려 returncode 0을 요구한다. import 시점의
  native crash는 자식 프로세스라야 보인다.
- `test_the_pre_4_7_aruco_api_detects_with_subpixel_corners` — `_LegacyAruco`가 4.6의 API 모양
  (`ArucoDetector` 없음, `DetectorParameters_create`, free `detectMarkers`)을 흉내 낸다. bare
  `DetectorParameters()`는 필드를 쓰면 예외를 던지는 `_NullPointerParameters`로 대신한다.
  이 테스트가 호스트 5.0에서도 4.6 경로를 지나게 한다.

main도 같은 장치 결함을 따로 만나 고쳤다(커밋 "fix(control): dock tag detection works on the
device's OpenCV 4.6"). 한 번 만난 사람만 아는 함정이라는 뜻이다.

## Why This Works

4.6의 Python 바인딩에서 파라미터 객체의 정상 생성 경로는 `DetectorParameters_create()`뿐이다.
`getattr`로 그 팩토리를 먼저 찾으면 4.6에서는 올바른 객체를, 팩토리가 없는 4.7+에서는 생성자를
쓴다. 검출기 역시 `hasattr(aruco, "ArucoDetector")`로 세대를 판별하므로 버전 문자열을 파싱하지
않는다.

## Prevention

- 호스트와 장치의 네이티브 라이브러리 버전이 다르면(여기서는 OpenCV 5.0 대 4.6) 장치 버전의 API
  모양을 흉내 내는 가짜 모듈로 그 경로를 호스트에서 한 번은 지나게 한다.
- 모듈 import 시점에 네이티브 객체를 만드는 코드는 자식 인터프리터에서 import하는 테스트로 지킨다.
  exit -11은 in-process 테스트로 잡히지 않는다.

## Related Issues

- [호스트 pytest가 초록이어도 Gazebo 인식 경로는 실제로 돌려서 렌더된 값을 재야 한다](../workflow-issues/sim-perception-green-host-tests-hide-live-gazebo-defects-2026-09-22.md)
