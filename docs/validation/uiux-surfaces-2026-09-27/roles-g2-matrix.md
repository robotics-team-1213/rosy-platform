# D-306 역할별 절차 화면 G2/G3 회차 — 2026-09-27

**판정: `/setup` HOLD, `/device` HOLD.** 이 회차는 Windows Chromium이 실제 FastAPI `create_app` + `CoreServices` fixture에 요청한 **LOCAL** 화면 증거다. `X:\DevTemp\rosy-uiux-d306-roles-g2\`의 PNG 54장과 `matrix.json`이 원본이다. fixture는 인증된 `/api/v1` GET 응답을 실제 앱에서 받은 뒤 지정한 증거·목록·오류 상태만 치환했다. 물리 로봇, ROS 실행, Host Agent 실물, 이미지 설치 또는 현장 근거가 아니다. X:의 캡처는 일회성이고 저장소에 보존되지 않는다.

## 범위와 방법

`ROSY_RUN_BROWSER_TESTS=1 python -X utf8 -m pytest src/hmi/dashboard/test/test_role_g2_browser.py -q -p no:cacheprovider`로 재생성한다. 뷰포트는 각 셀에서 1366×768·390×844 두 개다. 스크린샷은 전체 문서 길이를 찍으므로 모바일 절차의 세로 스크롤까지 보인다. 결과 JSON은 역할·표면·상태·뷰포트·파일명·패널 수·가로 넘침·E-stop 가시성·페이지 오류·대화상자 문구·POST 기록을 남긴다. `notices` 배열은 숨은 DOM 노드도 포함하므로 PNG의 실제 가시성과 함께 읽어야 한다.

| 역할·표면 | 상태 | 캡처 | LOCAL 관찰 |
|---|---|---:|---|
| 운영자 `/setup` | 정상, 빈 목록, 지연, 연결 끊김, 정보 없음, 기능 미지원, 일부 API 403, 일부 API 503, SAFE_STOP, 확인 취소 | 20 | 패널 4개. 위치 지연은 마지막 수신 초, 끊김·정보 없음은 각각 다른 차단 사유로 표시한다. 확인 취소는 대화상자 1회·POST 0건. |
| 관리자 `/setup` | 위와 동일 | 20 | 패널 5개. 도크 기록과 도크 등록 모두 세 증거 상태를 구분한다. 확인 취소는 대화상자 1회·POST 0건. |
| 관리자 `/device` | 정상, 빈 응답, Host Agent 사용 불가, 일부 API 403, 일부 API 503, 확인 취소 | 12 | 패널 6개. 네트워크·릴리스 상태/작업이 같은 절차 안에 있고, 거부·오류 문구를 표시한다. 롤백 확인 취소는 대화상자 1회·POST 0건. |
| 운영자 `/device` | 표면 권한 거부 | 2 | 패널 0개, 상단은 `권한 제한`, 허용된 `/console` 링크가 보인다. |

모든 54셀에서 `document.documentElement.scrollWidth - innerWidth = 0`, `pageerror = 0`, 상단 E-stop의 오른쪽 모서리가 화면 안에 있었다. 대표 이미지: `administrator-setup-delayed-390x844.png`, `administrator-setup-disconnected-390x844.png`, `administrator-setup-unavailable-390x844.png`, `administrator-device-normal-1366x768.png`, `operator-device-forbidden-390x844.png`. 전체 파일명은 `matrix.json`에 있다.

정상 `/setup` fixture는 기본 `core` profile의 Navigation/SLAM 미제공을 `true`로 바꿔 조작 가능 상태를 보여 준다. 이는 실제 장치 capability가 아니다. `empty`는 목록 응답만 빈 배열로 치환했다. `delayed`·`disconnected`·`unavailable`은 `/api/v1/robot/state`의 pose 증거를 치환했고, 지연에는 22초 전 수신 시각을 넣었다. `forbidden`·`error`는 절차의 일부 하위 API만 403·503으로 바꿨다. `safe_stop`은 상태 응답의 `mode`만 `SAFE_STOP`으로 바꿨다. 확인 대화상자는 Playwright가 닫았고 호출이 0건인지 확인했다.

## D-153 G3 8항

| 항목 | 이번 회차의 근거·판정 |
|---|---|
| 1 정직 | 미지원 조작은 비활성이고 운영자 `/device`에 관리자 패널이 0개다. 정상 fixture의 Navigation/SLAM은 합성값이라고 명시한다. **부분 충족**: `/device`의 요청 접수는 적용 완료 readback이 아니며 Host Agent 실물 없음. |
| 2 증거 상태 | `/setup` 도크 기록·등록은 지연(22초), 연결 끊김, 정보 없음을 구분하도록 수정했다. **HOLD**: 다른 패널 및 `/device`의 fresh/delayed/disconnected/unavailable 전체 필드 계약은 이 회차에서 검증하지 못했다. |
| 3 색 | 대표 캡처는 기존 어두운 토큰, 의미색과 상단 정지색을 사용한다. 이번 변경은 색 토큰을 수정하지 않았다. **부분 충족**: 모든 캡처의 색 대비 수치와 현장 조명은 별도 검증이 필요하다. |
| 4 위계 | 관리자 `/device`의 정보 읽기와 네트워크·릴리스 조작이 절차별로 분리되고, 모바일에서는 세로 흐름을 유지한다. **부분 충족**: 전체 54셀의 사람 시선 경로 검증은 없다. |
| 5 불가역 | `/setup` 맵핑 시작과 `/device` 롤백의 실제 네이티브 확인을 취소해 POST 0건을 확인했다. E-stop은 상단에서 보인다. **HOLD**: 네이티브 확인창 자체의 이미지와 물리 정지 readback은 없다. |
| 6 어휘 | 위치 증거 세 상태와 권한 거부의 다음 행동을 한국어 평문으로 쓴다. 설치자용 ROS·DDS 용어는 유지한다. **부분 충족**: 설치자 인터뷰는 없다. |
| 7 표면 질문 | `/setup`은 위치·목록·capability와 다음 조작, `/device`는 Host Agent 상태와 작업을 보여 준다. **HOLD**: SAFE_STOP을 넣어도 절차 화면에는 그 모드가 명시적으로 드러나지 않는다. 실제 장치 결과도 없다. |
| 8 표면 문법 | 54셀 가로 넘침 0, 절차의 세로 스크롤 허용, 상단 E-stop 가시성. 권한 거부에서 `/console` 복구 링크 제공. **부분 충족**: 키보드 전체 포커스 순서와 D-153 G3 사람 판단이 남았다. |

## 미촬영·미검증 셀과 다음 작업

- **최초 기동 진행 상태**: 비동기 응답이 도착하기 전 화면을 별도 촬영하지 않았다.
- **네이티브 확인창 이미지**: Playwright의 dialog 이벤트와 취소·POST 0건은 기록했지만 OS 대화상자를 PNG에 포함하지 못했다.
- **`/device` 지연·연결 끊김**: Host Agent API는 이번 fixture에서 `available`/오류로만 구분했다. 시각·나이 증거와 실제 재연결 흐름은 검증하지 않았다.
- **SAFE_STOP**: `/setup` 상태 응답을 치환해 캡처했지만 절차 화면에 SAFE_STOP 표시가 없었다. 표시 및 조작 적합성은 별도 설계·시험이 필요하다. `/device` SAFE_STOP 셀도 촬영하지 않았다.
- **권한·오류 범위**: 일부 하위 API의 403/503만 주입했다. 모든 절차와 저장 실패/readback의 조합은 빠져 있다.
- **G3 사람 평가·장치**: 운영자·설치자 평가, BENCH/DEVICE/FIELD 캡처, 실물 E-stop·도크·네트워크 전환 결과가 없다. 따라서 어떤 표면도 D-153 GO가 아니다.

이번 수정 범위는 `src/hmi/dashboard/panels/setup/docking.js`, `dock-admin.js`, `shell/shell.js`와 브라우저 시험이다. 공용 토큰·API·서버 권한·D-283 3영역은 바꾸지 않았다. 되돌릴 때 이 커밋의 역할 화면 파일과 회차 시험을 함께 되돌리면 된다.
