# Pilot 태블릿 재연결과 현재 APK 후보 — 2026-10-09

기준 소스: 로컬 `main` `2e78b40ad811fa143abbde1d9ae03e4804a1a135`. Lenovo TB-J606F 실기기를 ADB로 다시 연결하고 설치된 Pilot을 열어 화면을 촬영했다. 이 기록의 장치 주소와 발견된 로봇 식별자는 공개 저장소에 남기지 않는다.

| 확인 항목 | 결과 |
|---|---|
| 실기기 | ADB `device`, 1200×2000px / 240dpi. Pilot `.MainActivity`가 전경인 상태에서 캡처. |
| 설치본 | `versionName=0.1.0`, 마지막 갱신 2026-10-07 17:43:39(장치 시각), APK SHA-256 `e69fac43e2b08ad533073ebdc8d35da5ecdcc662e686e03855a2603db06cd578`. |
| 촬영 | 로봇 선택 화면에 2대가 발견되어 표시됨. 화면 PNG SHA-256 `a3c9b7d3126d465059980a06b26661ecbdf42bb2aca2e8675c121418e00e4e24`. 배터리 표시는 17%. |
| 현재 후보 | 격리 worktree에서 `:app:testDebugUnitTest :app:assembleDebug` 성공. JVM 12 suite / 93 tests, 실패·오류·건너뜀 0. APK SHA-256 `cd6bba74a9ee4b2f25772bbc02995de69091fdd183e198c9964dc4f39745cd22`. |
| 자산 출처 | 후보 APK의 `assets/pilot/`, `assets/common/` 50개가 기준 소스와 바이트 단위 일치. 설치본과 후보 사이 10개가 다름. 연결 화면, 주행 화면, 공용 요청·UI 자산이 포함됨. |
| 덮어쓰기 조건 | 설치본과 후보 APK의 서명 인증서 SHA-256 모두 `d70c067b8c2343a046a906af2bc1a41861df30dcbd8a93ce53c32b638b99c741`. 설치나 앱 데이터 변경은 수행하지 않음. |

원본은 `X:/DevTemp/projects/rosy-platform/2026-10-09--lenovo-reconnect/`에 보관한다. `pilot-foreground.png`, `pilot-installed.apk`, `build/app/outputs/apk/debug/app-debug.apk`, `gradle.txt`, `asset-diff.json`이 해당된다. 원본 화면에는 사설 로봇 식별자가 표시되므로 공개 저장소에 넣지 않았다. `asset-diff.json` SHA-256은 `9def212ce23f13acd62ee82a02090fd3a94bea12fd14f17e9769608b5169d83a`이다.

문서 검증: `test_network_topology_contracts.py`, `test_harness_contracts.py`, `test_document_placement.py`, `test_folder_layout.py` 합계 **136 passed, 1 skipped**, `known_failures.py` 기준 NEW 0. `rosy_harness.py lint`는 0 error / 23 기존 모듈 이력 warning. 출력은 같은 X: 폴더의 `pytest.txt`에 보관한다.

화면 평가: 설치본에서 로봇 선택과 다시 찾기 동작은 눈에 띄지만 발견 카드는 연결 가능 상태나 신원 확인 결과를 아직 보여 주지 않는다. 발견 2대와 실제 접속 성공을 같은 증거로 취급하지 않는다. 현재 후보의 실기기 레이아웃과 연결·주행 동작은 이 캡처로 평가할 수 없다.

현재 후보를 테스트 AVD에 설치해 별도 화면을 촬영하려 했으나 에뮬레이터가 부팅 완료를 기록한 뒤에도 ADB에 등록되지 않았다. 한 차례 메모리 지정 재시도 후 종료했다. 따라서 이번 회차의 **현재 후보 G2 화면 캡처는 없음**. 단위 테스트와 APK 자산 일치는 화면 검증을 대신하지 않는다.

판정: 설치본의 DEVICE 로비 관찰만 확인. 현재 후보의 DEVICE G2, 실제 연결·실패·복귀·주행 상태, 사용자 G3, 현장 수용은 **HOLD**. 다음 단계는 후보 설치를 승인받은 뒤 동일 태블릿에서 APK 해시를 다시 읽고, 움직임 명령 없이 연결 상태·화면 폭·실패 복귀를 촬영하는 것이다. 실제 운전과 비상 정지 해제는 이 검증에 포함하지 않는다.
