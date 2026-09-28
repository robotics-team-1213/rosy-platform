# D-306 역할별 절차 화면 G2/G3 회차 — 2026-09-27

**판정: `/setup` HOLD, `/device` HOLD.** 이 회차는 Windows Chromium이 실제 FastAPI `create_app` + `CoreServices` fixture에 요청한 **LOCAL** 화면 증거다. `X:\DevTemp\rosy-uiux-d306-roles-g2\`의 PNG 60장과 `matrix.json`이 원본이다. fixture는 인증된 `/api/v1` GET 응답을 실제 앱에서 받은 뒤 지정한 증거·목록·오류 상태만 치환했다. 물리 로봇, ROS 실행, Host Agent 실물, 이미지 설치 또는 현장 근거가 아니다. X:의 캡처는 일회성이고 저장소에 보존되지 않는다.

## 범위와 방법

`ROSY_RUN_BROWSER_TESTS=1 python -X utf8 -m pytest src/hmi/dashboard/test/test_role_g2_browser.py -q -p no:cacheprovider`로 재생성한다. 뷰포트는 각 셀에서 1366×768·390×844 두 개다. 스크린샷은 전체 문서 길이를 찍으므로 모바일 절차의 세로 스크롤까지 보인다. 결과 JSON은 역할·표면·상태·뷰포트·파일명·패널 수·가로 넘침·E-stop 가시성·페이지 오류·대화상자 문구·POST 기록을 남긴다. `notices` 배열은 숨은 DOM 노드도 포함하므로 PNG의 실제 가시성과 함께 읽어야 한다.

| 역할·표면 | 상태 | 캡처 | LOCAL 관찰 |
|---|---|---:|---|
| 운영자 `/setup` | 정상, 빈 목록, 지연, 연결 끊김, 정보 없음, 기능 미지원, 일부 API 403, 일부 API 503, SAFE_STOP, 확인 취소 | 20 | 패널 4개. 위치 지연은 마지막 수신 초, 끊김·정보 없음은 각각 다른 차단 사유로 표시한다. 확인 취소는 대화상자 1회·POST 0건. |
| 관리자 `/setup` | 위와 동일 | 20 | 패널 5개. 도크 기록과 도크 등록 모두 세 증거 상태를 구분한다. 확인 취소는 대화상자 1회·POST 0건. |
| 관리자 `/device` | 정상, 빈 응답, 원본 지연, Host Agent 연결 끊김, 시각 정보 없음, 일부 API 403, 일부 API 503, SAFE_STOP, 확인 취소 | 18 | 패널 6개. 네트워크·릴리스의 서버 판정과 원본 조회 나이를 표시하고, fresh 외에는 작업을 막는다. 롤백 확인 취소는 대화상자 1회·POST 0건. |
| 운영자 `/device` | 표면 권한 거부 | 2 | 패널 0개, 상단은 `권한 제한`, 허용된 `/console` 링크가 보인다. |

모든 60셀에서 `document.documentElement.scrollWidth - innerWidth = 0`, `pageerror = 0`, 상단 E-stop의 오른쪽 모서리가 화면 안에 있었다. 대표 이미지: `administrator-setup-delayed-390x844.png`, `administrator-setup-disconnected-390x844.png`, `administrator-setup-unavailable-390x844.png`, `administrator-device-normal-1366x768.png`, `operator-device-forbidden-390x844.png`. 전체 파일명은 `matrix.json`에 있다.

정상 `/setup` fixture는 기본 `core` profile의 Navigation/SLAM 미제공을 `true`로 바꿔 조작 가능 상태를 보여 준다. 이는 실제 장치 capability가 아니다. `empty`는 목록 응답만 빈 배열로 치환했다. `delayed`·`disconnected`·`unavailable`은 `/api/v1/robot/state`의 pose 증거를 치환했고, 지연에는 22초 전 수신 시각을 넣었다. `forbidden`·`error`는 절차의 일부 하위 API만 403·503으로 바꿨다. `safe_stop`은 상태 응답의 `mode`만 `SAFE_STOP`으로 바꿨다. 확인 대화상자는 Playwright가 닫았고 호출이 0건인지 확인했다.

## D-153 G3 8항

| 항목 | 이번 회차의 근거·판정 |
|---|---|
| 1 정직 | 미지원 조작은 비활성이고 운영자 `/device`에 관리자 패널이 0개다. 정상 fixture의 Navigation/SLAM은 합성값이라고 명시한다. **부분 충족**: `/device`의 요청 접수는 적용 완료 readback이 아니며 Host Agent 실물 없음. |
| 2 증거 상태 | `/setup` 도크 기록·등록은 지연(22초), 연결 끊김, 정보 없음을 구분한다. `/device` 네트워크·릴리스는 Host Agent 원본 조회 완료 UTC에 대한 CORE 판정을 표시한다. **부분 충족**: 다른 패널의 전체 필드와 실제 Host Agent·장치 전이는 검증하지 못했다. |
| 3 색 | 대표 캡처는 기존 어두운 토큰, 의미색과 상단 정지색을 사용한다. 이번 변경은 색 토큰을 수정하지 않았다. **부분 충족**: 모든 캡처의 색 대비 수치와 현장 조명은 별도 검증이 필요하다. |
| 4 위계 | 관리자 `/device`의 정보 읽기와 네트워크·릴리스 조작이 절차별로 분리되고, 모바일에서는 세로 흐름을 유지한다. **부분 충족**: 전체 60셀의 사람 시선 경로 검증은 없다. |
| 5 불가역 | `/setup` 맵핑 시작과 `/device` 롤백의 실제 네이티브 확인을 취소해 POST 0건을 확인했다. E-stop은 상단에서 보인다. **HOLD**: 네이티브 확인창 자체의 이미지와 물리 정지 readback은 없다. |
| 6 어휘 | 위치 증거 세 상태와 권한 거부의 다음 행동을 한국어 평문으로 쓴다. 설치자용 ROS·DDS 용어는 유지한다. **부분 충족**: 설치자 인터뷰는 없다. |
| 7 표면 질문 | `/setup`은 위치·목록·capability와 다음 조작, `/device`는 Host Agent 상태와 작업을 보여 준다. **부분 충족**: SAFE_STOP은 공통 상단에 표시되지만 실제 장치 결과는 없다. |
| 8 표면 문법 | 60셀 가로 넘침 0, 절차의 세로 스크롤 허용, 상단 E-stop 가시성. 권한 거부에서 `/console` 복구 링크 제공. **부분 충족**: 키보드 전체 포커스 순서와 D-153 G3 사람 판단이 남았다. |

## 미촬영·미검증 셀과 다음 작업

- **최초 기동 진행 상태**: 아래 후속 회차에서 6셀을 촬영했다. 현재 화면에는 안전 상태 확인 중 문구를 표시한다.
- **네이티브 확인창 이미지**: Playwright의 dialog 이벤트와 취소·POST 0건은 기록했지만 OS 대화상자를 PNG에 포함하지 못했다.
- **`/device` 실물 재연결**: LOCAL에서 지연·끊김·시각 없음 화면을 캡처했다. 실제 Host Agent 재연결과 작업 적용은 검증하지 않았다.
- **SAFE_STOP 물리 결과**: `/setup`과 `/device`의 공통 셸 표시를 LOCAL에서 캡처했다. 물리 정지, 해제, 재출발 가능 여부는 별도 장치 readback이 필요하다.
- **권한·오류 범위**: 일부 하위 API의 403/503만 주입했다. 모든 절차와 저장 실패/readback의 조합은 빠져 있다.
- **G3 사람 평가·장치**: 운영자·설치자 평가, BENCH/DEVICE/FIELD 캡처, 실물 E-stop·도크·네트워크 전환 결과가 없다. 따라서 어떤 표면도 D-153 GO가 아니다.

이번 수정 범위는 `src/hmi/dashboard/panels/setup/docking.js`, `dock-admin.js`, `shell/shell.js`와 브라우저 시험이다. 공용 토큰·API·서버 권한·D-283 3영역은 바꾸지 않았다. 되돌릴 때 이 커밋의 역할 화면 파일과 회차 시험을 함께 되돌리면 된다.

## 2026-09-27 D-309 역할 화면 안전 상태 보완

- `/setup`와 `/device`의 공통 셸이 CORE `/api/v1/robot/state`를 읽어 `SAFE_STOP` 또는 `safety.estop=true`를 상단에 표시한다. 상태 필드가 없거나 조회가 실패하면 `안전 상태 확인 불가`로 표시하며 이전 정상 상태를 재사용하지 않는다.
- 설정·호스트 관리 조회와 복구 조작은 유지한다. 이동 명령의 최종 허용은 CORE API가 담당한다. 상단 비상 정지 응답은 요청 접수, CORE 상태 재조회, 물리 정지를 구분한다.
- 역할 화면 로컬 매트릭스에 관리자 `/device` 안전 정지를 추가했다. 역할 매트릭스·진입·패키지 시험 8 passed (Windows LOCAL). 새 캡처는 X:의 일회성 증거이며 실물/물리 정지 검증이 아니다. 화면 전체 G2/G3와 DEVICE/FIELD는 HOLD다.

## D-309 후속 점검

- 현재 브라우저 fixture는 관리자 `/device` SAFE_STOP 2셀을 포함해 총 60셀을 캡처한다. `matrix.json`에서 페이지 오류와 가로 넘침은 모두 0건이다.
- Host Agent 요청 중 상태 조회가 갱신되면 네트워크·릴리스 버튼이 다시 활성화되어 두 번째 POST가 가능했다. 각 절차의 요청 완료까지 버튼을 잠그고, 상태 조회와 요청 완료 시점에 다시 평가한다. `test_host_operations_browser.py`는 지연된 POST 중 GET 갱신을 재현해 중복 요청이 없음을 확인한다.
- `/device` 값별 지연·끊김 셀은 아래 후속 회차에서 캡처했다. 화면은 Host Agent API의 증거 판정을 표시하며 자체로 `fresh`나 `delayed`를 만들지 않는다. 실제 Host Agent 적용·롤백, SAFE_STOP 물리 정지, G3 사람 평가는 HOLD다.

## 첫 기동 전체 화면 LOCAL 셀

실제 FastAPI `create_app` + `CoreServices`에서 정적 화면을 받고, 브라우저에서 매니페스트와 로봇 상태 fetch만 응답 전으로 보류했다. 운영자·관리자 `/setup`, 관리자 `/device`를 각각 1366×768·390×844로 촬영했다. `X:\DevTemp\rosy-uiux-d306-roles-g2\first-boot-matrix.json`과 PNG 6장이 일회성 원본이다. 모두 패널 0개, `화면을 불러오는 중입니다`, `안전 상태 확인 중`, E-stop 가시성, 가로 넘침 0, pageerror 0을 확인했다. 인증 토큰이 없는 `/setup`·`/device`에서는 안전 상태 문구와 패널을 노출하지 않았다. 이는 첫 응답 전 UI만 증명하며 CORE 상태나 물리 안전을 증명하지 않는다.

## Host Agent 원본 시각과 `/device` 증거 회차

`network.status`는 Host Agent에서 활성 연결·Wi-Fi 프로파일·wlan0을 동기 조회하고, `release.status`는 `rosy-release status --json`을 동기 조회한다. 각 명령이 완전한 결과를 낸 직후 Host Agent가 `observed_at` UTC를 기록한다. 부분 nmcli 실패나 릴리스 상태의 파싱·필수 필드 실패는 정상 결과가 아니다. CORE는 각 응답의 원본 시각을 검증해 15초 이내 `fresh`, 15초 초과 `delayed`, 소켓 미연결·타임아웃 `disconnected`, 시각 누락·파싱 실패·미래 시각 `unavailable`을 판정하고 나이를 전달한다. 브라우저는 판정과 나이만 표시한다.

관리자 `/device`의 지연·연결 끊김·정보 없음 × 1366×768·390×844 6셀을 기존 매트릭스에 더해 총 60셀이다. `matrix.json`에서 pageerror·가로 넘침은 0건이고 세 상태 모두 네트워크 작업이 비활성이다. fixture는 정상 API 응답을 받아 상태 부분만 합성했으므로 실제 Host Agent readback이 아니다. 별도 실물 점검에서 기존 로봇 릴리스에는 `rosy-host-agent.service` unit과 소켓이 없고 CORE 두 GET은 `HOST_AGENT_UNAVAILABLE`이었다. 새 이미지·서비스 배포와 실물 네트워크/릴리스 결과는 **DEVICE HOLD**다. G3 사람 평가도 HOLD다.


## 2026-09-28 localization pending follow-up

After `b3d8e6cd`, a panel browser regression verified that the 10-second localization capability poll preserves pose/SLAM pending locks and action feedback, and repeated requests do not issue duplicate POSTs. The full panel suite passed **14 tests**. Role G2 passed **5 tests** and refreshed 60 cells: overflow 0, pageerror 0, E-stop visible 70/70, canceled confirmation POST 0. Administrator `/setup` full-shell captures at 1366x768 and 390x844 were visually inspected. PNGs and `matrix.json` are under `X:\DevTemp\rosy-uiux-d306-roles-g2\`.

These are browser and mock/local API results. Actual pose/SLAM readback, physical E-stop, and user G3 evaluation remain separate; product acceptance, DEVICE, and FIELD stay **HOLD**.


## 2026-09-28 administrator /device security follow-up

The focused security-panel Chromium regression verified token-list clearing after poll and mutation-triggered GET failures, independent create/delete feedback, one-time secret retention across token-list and safety polls, dirty-form retention on the 15-second safety readback, save-time controls locked, and fields updated from the CORE PUT response. It exposed a stale-list case after successful create/delete followed by failed list refresh; the panel now clears/hides that list through the shared unavailable handler. The full panel suite passed **15 tests**.

Current-main role G2 passed **5 tests** with 60 cells, overflow 0, pageerror 0, E-stop visible 60/60, canceled confirmation POST 0. Administrator `/device` full-shell captures at 1366x768 and 390x844 were visually inspected. JSON/PNGs are in `X:\DevTemp\rosy-uiux-d306-roles-g2\`. This is LOCAL browser evidence; real Host Agent, safety CORE/device readback, physical E-stop, and G3 remain separate.

## 2026-09-28 host readback and console mode feedback follow-up

The `a81dbcb2` Host Agent panel and `3b89deeb` `/console` mode panel updates were verified in Chromium. Focused panel regressions exercised independent runtime, identity, capability, and inventory GET failures and verified that each failure cleared only its corresponding stale readback. The console regression overlapped mode/capability polling with a pending MANUAL POST, verified the accepted POST remained separate from IDLE readback, then updated mode readback and failed capability read without erasing the action result.

Current local G2 passed **6 tests** and refreshed **60 cells** across operator/admin, `/setup` and `/device`, configured state scenarios, and 1366x768/390x844 viewports. Overflow 0, pageerror 0, and E-stop visible 60/60. Additional full-shell `/console` mode-feedback captures at both viewports recorded one MANUAL POST each, IDLE readback at acceptance, overflow 0, no page errors, and visible E-stop. Administrator `/device` normal captures and both console captures were visually inspected. `matrix.json`, `console-mode-feedback-matrix.json`, and PNGs are under `X:\DevTemp\rosy-uiux-d306-roles-g2\`.

The fixtures use local FastAPI/Chromium responses. Actual Host Agent and physical robot mode readbacks, physical E-stop, G3 evaluation, and DEVICE/FIELD acceptance remain **HOLD**; this evidence does not advance D-153 or D-255 B2/B3.

## 2026-09-28 console teleoperation readiness and action feedback

The `1af1fa41` `/console` teleop follow-up was checked with focused panel regressions and a full-shell Chromium capture. The panel regressions exercised hold, release, forced stop, timeout, and terminal-zero delivery failure while polling updates ran. They also injected state, capability, safety, and commissioning GET errors one at a time, verified each reason stayed in the readiness region, and confirmed successful readback cleared only the recovered reason without overwriting the action result.

The full panel browser suite passed **19 tests**. Role G2 passed **7 tests**, refreshing 60 cells with overflow 0, pageerror 0, E-stop visible 60/60, and canceled-confirmation POST 0. Full-shell teleop captures at 1366x768 and 390x844 show a robot-state read failure beside the preserved release/stop feedback; each recorded one terminal zero POST, overflow 0, no page errors, and visible E-stop. The test fixture adds `console.teleop` to the console manifest because its local profile does not advertise teleop, and provides controlled mock/local API responses. Screenshots and `console-teleop-feedback-matrix.json` are under `X:\DevTemp\rosy-uiux-d306-roles-g2\`.

These are LOCAL browser results only. Actual motion and stop readback, physical E-stop, G3, DEVICE/FIELD, and D-153 acceptance remain **HOLD**.

## 2026-09-28 line-follow and docking feedback

Focused Chromium tests passed for line-follow stale-read clearing, fail-closed controls, independent Navigation capability feedback, pending locks, and POST/readback separation; docking tests covered stale status/list clearing, selected-dock retention, and control locks during polling. The full panel suite passed **21 tests**. Role G2 passed **8 tests** and refreshed **60 cells** with overflow 0, pageerror 0, E-stop visible 60/60, and canceled-confirmation POST 0.

Full-shell console captures at 1366x768 and 390x844 show line-follow and docking in their own action groups. Each capture shows a status-read failure beside a preserved CORE request receipt, with one expected action POST, overflow 0, no page errors, and visible E-stop. The fixture explicitly inserts both panels and their action groups into the console manifest and controls API responses. PNGs and JSON are under `X:\DevTemp\rosy-uiux-d306-roles-g2\line-follow-docking\`.

This is LOCAL browser evidence. Actual robot line-follow/docking readback and motion, physical E-stop, G3, DEVICE/FIELD, and D-153 acceptance remain **HOLD**.

## 2026-09-28 console map feedback verification

Focused map-panel Chromium regression passed within the **22 passed** full panel suite. It covered separate robot/capability/commissioning errors, map-data freshness, a no-map target click with no confirmation or POST, and accepted/failed target feedback retained through explicit map refreshes. Full-shell captures at 1366x768 and 390x844 show the empty-map state beside robot-state readiness failure and the not-sent action result. Both have horizontal overflow 0, no page errors, and visible E-stop. Artifacts are in `X:\DevTemp\rosy-uiux-d306-roles-g2\map-data-action\`.

The full G2 command reported 8 passed and 1 failed in an administrator `/device` `confirm_cancel` fixture (rollback control unexpectedly disabled); it did not complete a new 60-cell matrix. This case is outside the map panel. The dedicated map regression and captures pass; robot map/target readback, physical E-stop, G3, DEVICE/FIELD, and D-153 remain **HOLD**.

## 2026-09-28 administrator board hardware refresh feedback

Focused Chromium panel regression passed **1 test**. During a pending refresh POST, measurement polling updated independently; accepted request receipt persisted across later measurements, and POST error remained visible after measurement-read failure. The dedicated full-shell capture test passed at 1366x768 and 390x844. Both screenshots were visually inspected: horizontal overflow 0, page errors 0, E-stop visible. Controlled local fixture only; full G2 matrix was not rerun. Artifacts: `X:\DevTemp\rosy-uiux-d306-roles-g2\host-hardware-refresh\`.

SOURCE/LOCAL browser verification is complete for `17f30137`. Actual Host Agent readback, physical device completion, G3, DEVICE/FIELD, and broader D-153 acceptance remain **HOLD**.

## 2026-09-28 administrator identity editor polling regression

Focused Chromium panel regression passed **1 test**, confirming 30-second identity callback updates keep exactly one form, preserve the unsaved draft, lock editing during PUT, and retain request feedback through stale readbacks. Dedicated full-shell captures passed at 1366x768 and 390x844; both were visually inspected with overflow 0, pageerror 0, and visible E-stop. The local fixture accelerates the identity poll and uses controlled API replies. This did not rerun the full G2 matrix. Artifacts: `X:\DevTemp\rosy-uiux-d306-roles-g2\admin-device-identity-feedback\`.

SOURCE/LOCAL browser verification is complete for `df260822`. Physical identity readback, G3, DEVICE/FIELD, and broader D-153 acceptance remain **HOLD**.

## 2026-09-28 board hardware permission hint reachability

Current-main focused Chromium regression passed for the administrator path: `aria-describedby` points to the initially hidden action status, which appears after refresh interaction. Admin full-shell refresh captures passed at 1366x768 and 390x844. The operator full-shell role check also passed at both widths, showing the `/device` access-denied screen and no `host.hardware` or `host.operations` panel; those denial captures were visually inspected. Artifacts: `X:\DevTemp\rosy-uiux-d306-roles-g2\operator-device-entry-denied\` and `X:\DevTemp\rosy-uiux-d306-roles-g2\host-hardware-refresh\`.

`fb2b220c` removed the non-admin button hint after confirming `/device` and `host.hardware` are administrator-only. Therefore the `b61fb526` disabled-button description cannot be reached by non-admins in the current role model. Browser evidence does not verify that reported affordance. Full G2 was not rerun; actual Host Agent readback, G3, DEVICE/FIELD, and D-153 remain **HOLD**.

## 2026-09-28 latest-main role G2 rerun

After main reached `a3d4c1f9`, `ROSY_RUN_BROWSER_TESTS=1 python -X utf8 -m pytest src/hmi/dashboard/test/test_role_g2_browser.py::test_role_procedure_g2_local_matrix -q` passed (**1 test, 60 role/state/viewport cells**). The generated `X:\DevTemp\rosy-uiux-d306-roles-g2\matrix.json` records pageerror 0, horizontal overflow 0, and E-stop visible in all 60 cells. The administrator `/device` release rollback confirmation was enabled at both 1366×768 and 390×844; cancel produced one dialog and zero POSTs in both cells. This supersedes the earlier matrix attempt that stopped at the disabled rollback control.

This is local FastAPI/Chromium fixture evidence. It does not prove Host Agent release rollback, robot identity or mode readback, physical E-stop, G3 human acceptance, or DEVICE/FIELD status; those gates remain **HOLD**.

## 2026-09-28 G2 rerun on `757fb38f`

The first run stopped at administrator `/device` `confirm_cancel` because the test asserted rollback availability immediately after panel creation. Host release polling was still pending. The fixture already supplies a fresh release record with previous version `r1`; I made the test wait for that readback and enabled rollback before exercising cancel.

Rerun: `ROSY_RUN_BROWSER_TESTS=1 python -X utf8 -m pytest src/hmi/dashboard/test/test_role_g2_browser.py::test_role_procedure_g2_local_matrix -q` ? **1 passed, 60 cells**, overflow 0, pageerror 0, E-stop visible 60/60. `X:\DevTemp\rosy-uiux-d306-roles-g2\matrix.json` contains the completed run.

This is local FastAPI/Chromium fixture evidence. Physical E-stop, actual Host Agent release operation, G3, DEVICE/FIELD, and D-153 remain **HOLD**.
