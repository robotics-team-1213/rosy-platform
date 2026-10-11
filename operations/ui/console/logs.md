# console_source verification log

## 2026-10-11 · 0702cdb15 · uiux: 선택 로봇의 배정·진행 작업면 (D-651)

- 변경: 지도 작업면과 선택한 로봇 작업면을 나눴다. 선택은 명령과 분리하고 선택 변경 시 이전 목표 지정·미확정 명령을 취소한다. 기존 경로·한 바퀴·반복 입력은 종류별로 하나씩 표시한다. 지도 장소·신호는 번호·아이콘으로 줄이고 좌표·교통과 기술 옵션은 지도 밖 접힘으로 옮겼다. 전체 취소·개입 큐와 전체 로봇 연결·안전·교정 요약은 보존한다.
- 증거: 작업 구현 c54272b84 원격 Chromium 포함 관련 7개 suite 89 PASS, known_failures NEW 0; Node 288 PASS. 별도 convoy·개발 연결·page/session lifetime·overhead tracking 25 PASS, NEW 0. 4개 크기 관측 만료·상세 좌표 배치와 실제 요청 확인·readback 검증을 수행했다. 독립 finish review는 유효한 desktop/mobile 캡처 13장을 검토해 ship, material fixes none; 문서 감사는 기존 역할 토큰과 D-651 방향의 일치를 확인했다.
- gate 변화: SOURCE/원격 작업 흐름 GO. 통합 전체 회귀·main 착지·push·CI·서명 배포·배포된 실제 지도 검증은 후속 gate다. 실제 로봇은 오프라인이며 이동·AprilGrid 실측 정확도는 승인하지 않는다. 관측 유효 픽셀 비율은 정확도 지표가 아니다.
- 현장 프로필: 기존 map_v2_fleet v5를 map_v2_fleet-v5 차선 코스 프로필로 저장하고 목록 및 API GET 200을 확인했다. 활성 지도 v5와 SHA cd13474068721637c1824f7b97422eef6370fd3ca5c3788433d060b159acf94f는 그대로다.

## 2026-10-11 · e58d7c4f52 · refactor: 사건 근거·검토 패널 소유 분리 (D-362/D-641)

- 변경: 사건 표시·검토·조회·JSON 내보내기와 접속 변경 시 초기화를 `incident-view.js`로 추출했다. Console은 인증·폴링 운율·명령을 소유하고 기존 page scope, call, log, view, auth를 주입한다. 기존 함수 본문과 API·권한·취소 흐름을 보존하며 정적 자산 allowlist와 문서 소유·설치 자산 시험을 함께 갱신했다. console.js 994줄, incident-view.js 219줄, Fleet production 52083줄이다.
- 증거: 자원 기준을 통과한 AI PC에서 e58d7c4f52로 원격 pytest 36 PASS, known_failures NEW 0. 기존 16개 브라우저/Node wrapper, 문서 import·HTTP 자산, wheel·sdist 설치 source parity, 접속·페이지 lifetime 브라우저를 포함한다. X:/DevTemp/ui-incident-view/run-2.txt.
- gate 변화: SOURCE/원격 브라우저·설치 자산 GO. 공식 main 착지·push·CI·배포·실물 주행 수용은 별도다. 기존 Console 1175 상한과 zero-growth 및 CORE 최종 명령 권한은 유지한다.

2026-10-11: D-637 folder move in progress; committed-SHA verification pending.

2026-10-11: source d4988bffba landed on local main after independent review, remote regressions/known_failures 0 NEW and installed wheel/sdist/HTTP proof. SOURCE/LOCAL GO only; CI FULL and ROS-SIM/ARM64/device/field remain unverified. See docs/validation/d637-remaining-folders-2026-10-11/result.md.

## 2026-10-11 · 92592fc2ef · uiux: 운영 요약과 사건 근거·진단 분리 (D-641)

- 변경: 현재 정체와 알림은 상태·판단 주체·다음 조치를 먼저 보여 주고, 관측·영상과 원시 응답/JSON을 각각 native disclosure로 보존한다. 과거 사건은 기본 접힘이며 검토 저장·내보내기와 권한 계약을 유지한다. AI 사실을 영상 해석으로 단정하지 않고 전달 실패·결과 미확인·로봇 거절·수락을 구분한다. 같은 문의의 갱신은 펼침·포커스를 보존하고 새 문의는 펼침을 초기화한다.
- 증거: 원격 현장 PC 자원 기준 통과 후 92592fc2ef에서 Console queue 브라우저 전체, Node 웹 단위 시험 wrapper, 기존 line-stuck 브라우저 3개를 실행했다: pytest 16 PASS, known_failures NEW 0. X:/DevTemp/ui-shell-evidence/run-3.txt. 320/390/1366 새 근거 흐름과 기존 1920/1366/390/320 맥락 탭 흐름을 포함한다.
- gate 변화: SOURCE/원격 브라우저 GO. 실제 로봇 명령·주행, CI·배포·기기·현장 수용은 시행하지 않았다. 수락으로 실행 완료를 확정하지 않는다.

2026-10-11: keep traffic/coordinate readouts at a fixed height while the desktop map fills the remaining panel height; avoid wide-screen overflow without changing expired-coordinate behavior. Update the site-map browser API fixture for saved map settings. Committed remote Chromium and deployment verification follow.

2026-10-11: use numbered place dots instead of floor name/coordinate paragraphs; keep place names, traffic and calibration diagnostics in a desktop sideboard that stacks below the map on compact screens. Preserve every calibration warning and its authority outside the floor plane. Browser regression covers names off the plane, responsive placement and expired-coordinate frame stability.

## 2026-10-11 · fb54c9f47f · fix(ci): 사건 인수 버튼 종류·비활성 사유

- 문제: main 4bcfc55d88의 CI 38147167947에서 incident-view 인수 버튼의 kind와 처리 중 비활성 사유가 빠져 공용 UI 계약 두 건이 실패했다.
- 변경: 기존 ui-button에 quiet 종류와 처리 중 사유를 명시한다. 기존 권한 검사·중복 요청 차단·요청 본문·갱신·오류 처리는 유지한다.
- 증거: 같은 기준 SHA의 원격 RED 2 NEW 뒤 수정 SHA에서 공용 UI 계약과 Fleet 사건/알림 시험 61 PASS, NEW 0. 독립 리뷰가 fb54c9f47f의 세 파일을 승인했다.
- gate 변화: SOURCE/원격 관련 회귀 확인. main 통합·새 CI·배포·주행 수용은 별도다.

## 2026-10-11 · 9e68d078b · D-655 빈 지도 조사 초안 입력

- 변경: 기존 site-map에 기준점·방향·축척 근거, 장소·도로·신호등·정지선·랜드마크·금지 영역 추가/수정/삭제를 연결했다. 시설은 작은 지도 기호로, 이름과 연결 차로는 지도 밖 목록으로 보여 준다. 명시적 검토 뒤 편집하면 검토를 무효화한다. 새 일반 프로필은 임의 예제 도로를 생성하지 않는다. 활성 지도와 로봇 명령은 기존 경로가 소유한다.
- 증거: 48a2fbfc1 원격 Chromium 4 PASS/NEW 0, 1440/390 px 빈 초안 생성·저장·재조회와 축구장 프로필. 935306768 Node 22 PASS, harness 0 errors/23 기존 경고. 전체 지도 Chromium은 연결 중단 뒤 분할해 ea60284994 A 36 PASS와 6b89d6cb38 B 25 PASS, 합계 61 PASS/NEW 0이다. 두 SHA 사이 해당 UI/browser/transport 소스 차이 없음. B의 runner non-site 자원 fallback 경고는 기준 통과로 보고하지 않는다.
- gate 변화: 입력 화면 소스와 일부 원격 검증. 주행 조사·카메라 누적·선택 로봇 대형 연결, 최종 통합·서명 배포·실제 현장 정확도는 별도 작업이며 이 기록은 배포 증거가 아니다.

## 2026-10-11 · 8596f7042b · D-655 상대 주행 조사 화면 연결

- 변경: 지도 가르치기에 확인된 지도 위치/상대 주행 조사 선택과 실제 시작점·방향 확인을 연결했다. 저장 revision·로봇·방식 변경과 매 시작에서 확인을 초기화한다. 기준 설명은 지도 밖에 두며 기준 snapshot이 같은 지도에만 관측 선을 표시하고 다른 초안에 확정을 막는다. 단절은 기록 중단으로 표시하고 실제 로봇 정지와 구분한다. 멈춘 result의 점 개수와 좌표 배열을 구분해 미리보기 선을 유지한다.
- 증거: Node RED 뒤 24 PASS; 3c8a1fe713 missing control RED 뒤 새 UI 흐름, 멈춘 선 미리보기 추가 RED 수정 후 8596f7042b Chromium 6 PASS/NEW 0. 1440/390 px UNKNOWN 로봇의 기록 시작→초안 선 표시→확정과 기존 수동 지도·축구장 프로필을 확인했다. source 1a14e9705a의 API 37 PASS/NEW 0. 임의의 운영 위치 승인이나 이동 명령은 생성하지 않는다.
- gate 변화: source/remote UI. 현재 main 통합 회귀, 설치 자산·CI·서명 배포·실제 사이트·현장 정확도/대형 주행은 아직 확인하지 않았다.

## 2026-10-11 · 7476837977 · D-655 분류별 요소 편집과 기록 프레임 표시

- 변경: 지도 요소 선택과 삭제를 분류+ID로 식별해 허용된 분류 간 같은 ID를 보존한다. 일반 기록과 조사 기록 모두 시작 snapshot에 맞는 지도에서만 미리보기 선을 그린다. 초안 편집 계산은 site-map-edit.js가 소유하고 지도 표시 모델과 분리했다.
- 증거: 독립 검토 뒤 같은 ID 보존과 일반 기록의 다른 profile 표시 거절 Node 26 PASS. API frame guard와 정상 조사 편집/활성 버전 변경 remote 55 PASS/NEW 0. desktop/mobile 브라우저 재검증은 별도 terminal 결과로 기록한다.
- gate 변화: source/remote; main 통합·CI·설치 자산·배포·실제 관제 및 실물 정확도는 미확인이다.
- 최종 표시 근거: 73295afa26 desktop/mobile Chromium 8 PASS/57 deselected, NEW 0; d871a9842e 구조 3 PASS/35 deselected, NEW 0. AI PC 자원 기준 통과. X:/DevTemp/projects/rosy-platform/2026-10-11--194243--mapless-fleet-control--384416/logs/survey-review-browser-final/run-1.txt.

## 2026-10-11 · ebf05b9811 · D-655 카메라 관측 누적과 근거 보존

- 변경: 초안 교체와 별도 누적 조작을 연결했다. 저장된 초안과 전체 조사 기준·map_id를 비교하고 기존 시설·규칙·간선을 보존한다. 반복 기하는 중복 생성하지 않고 다른 프레임 근거는 보존하며 재검토한다. 수동 도로/장소 교정·검토에서도 원본 지문을 유지한다. 조사 없는 camera map의 검토도 기존 메모 조작으로 연결했다. 모호한 endpoint는 자동 접합하지 않는다.
- 증거: 실제 control RED 뒤 7d3a93d0f2 9 PASS, 독립 검토 세 근거 수정 뒤 ebf05b9811 desktop/mobile 누적·검토 저장·재편집 활성화 거절과 marker/Vision/구조 12 PASS/NEW 0. Node 28 PASS. X:/DevTemp/projects/rosy-platform/2026-10-11--194243--mapless-fleet-control--384416/logs/camera-review-final-retry/run-1.txt. AI PC 자원 기준 통과.
- gate 변화: source/remote. endpoint 연결 후보 검토·작업/대형·개입·통합·CI·배포·실제 관제/측정은 계속 작업한다.

## 2026-10-11 · 962fa15277 · D-655 reviewed camera connections and pending writes

- 변경: 지도 밖 연결 후보·거리·선택·실제 연결 확인을 focused site-map-camera.js가 소유한다. 선택한 장소 ID를 유지하며 파일·초안·미저장 편집·선택·접속 변경이 대기 중 저장을 취소한다. 활성 지도와 이동 권한을 바꾸지 않는다.
- 증거: Node 29 PASS, 자원 기준 통과 AI PC Chromium 16 PASS/63 deselected, NEW 0. desktop/mobile 파일 읽기와 교체 확인 창 경합에서 이전 요청이 저장되지 않는다. terminal 로그는 `X:/DevTemp/projects/rosy-platform/2026-10-11--194243--mapless-fleet-control--384416/logs/camera-connect-race-green/run-1.txt`. 독립 검토 두 Important 수정 후 수용.
- gate 변화: source/remote 범위. 선택 로봇 작업·대형 연결, 개입, 통합·배포·실제 사이트 수용은 계속 진행한다. 실물 측량 정확도는 미확인이다.

## 2026-10-11 · a1b850f7d · D-655 selected recording and group workspace

- 변경: 선택 로봇 ID를 지도 기록으로 전달하고 기존 대형 패널을 작업 카드에서 연다. 리더/팔로워는 실제 상태에서 표시한다. 진입 시 제출 전 확인·운행 폼·목표·위치 지정만 취소하며 명령은 보내지 않는다. 요청 ID 없음/등록 제거는 다른 로봇으로 대체하지 않는다. 사용자 선택은 새로고침에서 유지하고, 기록 중에는 실제 기록 로봇과 중단 조작을 유지한다. 오프라인 대상은 연결 끊김으로 표시한다.
- 증거: 새 경로 RED 3 FAIL 뒤 6 PASS. 넓은 회귀 158 PASS/2 fixture FAIL은 목표 미지원 fake를 누른 시험이어서 지원하는 운행 폼으로 수정했다. 기록 대상 RED 뒤 최종 자원 기준 통과 AI PC 역할/배정/대형/대상/지도/구조 30 PASS/111 deselected, NEW 0 (`X:/DevTemp/projects/rosy-platform/2026-10-11--194243--mapless-fleet-control--384416/logs/selected-context-acceptance/run-1.txt`). 독립 소스 검토 수용.
- gate 변화: source/remote 진입·대상 유지 범위. Task 5 충돌 및 지도 활성화 busy 보강, main 통합·CI·배포·실제 사이트·실물 수용은 남아 있다.


## 2026-10-11 · d6abc8e863 · D-655 map activation and command conflicts

- 변경: trip뿐 아니라 진행 중 대형과 지도 기록에서도 활성화를 거절한다. 일반 기록 시작·pose 장소 저장은 위치 조회 전후 map_id·전체 조사 기준·활성 버전을 비교해 이전 위치의 새 지도 저장을 막는다. 팔로워 목표와 참여자 개별 운행, 진행 중 trip의 개별 목표를 기존 admission에 맞춰 설명하며 확인 직전 재검사한다. 충돌 작업을 자동 해제하거나 이동 명령을 추가하지 않는다. 재개·후진 수락과 실제 로봇 진행을 구분한다.
- 증거: busy RED 4 FAIL, start 경합 RED 뒤 131 PASS, place fixture의 같은 위치로 SITE_MAP_INVALID가 난 경우를 구분하고 distinct pose에서 실제 DID NOT RAISE를 재현했다. 공통 수정 a4a9e2f9e 132 PASS/NEW 0. 대형 화면/서버/구조 68 PASS, 개입·부분 취소·불명 응답·운행 권한·위치 손실 253 PASS/NEW 0. 최종 d6abc8e863 Chromium 역할/대형 및 teach/활성화/구조 140 PASS/NEW 0, 모델 PC 22 cores/7.9 GB 기준 통과. UI Node 301 PASS. 넓은 Node 첫 실행의 누락 loader 오류는 기존 loader를 지정해 해결했다.
- 근거 위치: X:/DevTemp/projects/rosy-platform/2026-10-11--194243--mapless-fleet-control--384416/logs/task5-command-final/run-1.txt; logs/task5-intervention/run-1.txt; logs/task5-node-final.txt. 독립 survey_feature_review가 shared guard·모든 UI 호출자·권한 보존을 수용했다.
- gate 변화: Task 4/5 source·원격 범위 완료. main 폴더 이동 통합·전체 회귀·CI·서명 릴리스·배포·실제 사이트 확인은 Task 6이며 목표는 active다. 실제 로봇 주행·측량·대형 개입 수용은 미확인이다.

## 2026-10-12 · 17758e2b29 · Console 운행 위치·계획 제출 재검사

- 변경: 알려진 현장 지도 위치 불명·추정·좌표 누락·지도 버전 불일치를 계획/출발 조작에서 안내한다. CORE의 명시적 map LOCALIZED fallback, 구형 Fleet의 guide 미지원, operator_pin 출처, 서버 admission을 유지한다. guide 조회 실패는 이전 위치를 실행 근거로 재사용하지 않는다.
- 변경: route·한 바퀴·반복·대열 모두 출발 POST 직전 현재 권한·안전·대형·위치·계획 버전·만료·진행 운행을 다시 검사한다. 목적지 또는 출발·경유지가 달라진 지연 미리보기는 채택하지 않는다. 포커스로 유지한 카드에서도 같은 로봇의 거절 안내만 갱신한다.
- 증거: 85632eeade Node 305 PASS, 원격 서버/운행 계약 153 PASS/NEW 0. 원격 Chromium 108개 중 focused SELECT의 안내 누락 3 NEW를 재현했고 출발 POST는 0이었다. 17758e2b29에서 안내 갱신 후 card Chromium 19 PASS/NEW 0, Node 305 PASS. 독립 소스 검토는 두 커밋을 수용했다. 로그는 `X:/DevTemp/projects/rosy-platform/2026-10-11--212133--wall-stop-cross-sim--126256/logs/console-browser-fixed/run-1.txt`와 같은 세션의 `console-contracts/run-1.txt`다.
- gate 변화: 원격 브라우저는 실제 Fleet 정적 자산과 fake API를 사용한다. 배포된 Console, 실물 주행, 두 대 Fleet 또는 Isaac 카메라 강화학습 완주를 대신하지 않는다. main 통합 후 수용·원격 CI는 별도 확인한다.

## 2026-10-12 · 22b307c07 · fix(cell): 미구성 서비스의 다음 행동과 재접속 복구

- 변경: Cell 서비스 미구성 응답을 받은 뒤 서버가 필요한 문서·미리보기·작업 조작을 비활성화하고 구성 확인 사유를 표시한다. 계정 접속·로컬 문서 입력·비상정지는 유지하고 성공한 재접속 문서 조회 뒤 기존 역할·문서·작업 조건으로 돌아간다.
- 증거: 설치본 Cell이 미구성 안내와 활성 저장 조작을 함께 보이는 것을 확인했다. 회귀에 차단 이유·비상정지/접속 유지·재접속 복구를 추가했다. 첫 통합 회귀의 접힌 접속 조작 클릭 실패는 기존 공용 펼침 helper를 사용해 수정했으며 실패 목록에 추가하지 않았다. 적정 자원 최종 회귀와 설치본 증거는 별도 기록한다.
- gate 변화: SOURCE 개선이며 새 커밋의 main 착지·push·CI·서명 설치·실제 Cell 작업 수용은 별도다.

## 2026-10-12 · bbc523dc6 · uiux: 전체 활성 표면 통합 검증

- 변경: 기존 역할별 헤더와 본문 흐름을 검토하고 Cell 미구성 복구, Pilot 상태 근거와 연결 순서, Robot 재시도/권한 판독, Learning 작은 헤더, Android 함께 조종 안내를 통합했다.
- 증거: 적정 자원 원격 통합 342 passed, 계약·문서 64 passed, 작은 헤더/Cell 캡처 9 passed, Robot/Pilot 단계별 176/27/3/8/3 passed, 각 known_failures NEW 0. Android 106 tests와 APK 빌드 통과. 변경 후 캡처와 기존 설치본 Fleet 8 화면 조합의 직접 검토를 docs/validation/all-ui-workflows-2026-10-12/result.md에 구분해 기록했다.
- gate 변화: SOURCE·원격 회귀·변경 후 렌더링 근거다. 기존 설치본 확인은 새 변경의 배포 증거가 아니다. 새 main 착지·push·CI·서명 설치 및 실물 장치/현장 수용은 별도다.

## 2026-10-12 · 7a0725de4 · fix(ui): 현장 복구 목표와 공용 실패 안내

- 변경: 사용자가 현장 운용·오류 복구를 우선 선택해 대상→현재 근거→막힌 이유→가능 조작→실제 결과 재확인으로 목표를 정했다. impeccable context/audit/clarify와 frontend-ui-engineering으로 기존 역할·캡처·공용 계약을 평가했고, 서버/연결 실패에 현재 상태 재조회 안내를 공용 Fleet 요청 어댑터에서 제공한다.
- 증거: Node 새 회귀 변경 전 3 FAIL, 변경 후 요청 계약 포함 33 PASS. detector 12건은 동적 이미지·계약된 탐색·누락된 경로 해석의 영향을 확인했다. docs/plans/2026-10-12-field-ui-recovery-brief.md에 평가 범위와 미확인 성능/실물 경계를 적었다. 관련 브라우저 회귀와 main 통합 재검사는 이어 실행한다.
- gate 변화: SOURCE/Node 근거다. 사용자 main 착지·push·배포 확인 지시를 받았으며 적정 자원 시험·CI·서명 설치·실제 화면 증거를 따로 확인한다.

## 2026-10-12 · 80a12948c · test(ui): 실제 조작 목적과 처리 완료를 관측

- 변경: 최신 로봇 맥락 탐색 조작과 목표 지정 조작을 데이터 속성으로 구분한다. 헤더의 현재 역할은 접힌 접속 입력과 구분하며 D-658의 항상 접힌 화면 설정 상세를 검사한다. 지도 초안 재저장은 이전 저장 표시를 완료로 오인하지 않고 해당 PUT 응답을 기다린 뒤 원장을 확인한다. 연결 실패는 현재 상태 재조회 안내를 검사한다.
- 증거: 적정 자원 원격 후보 80a12948c에서 15 NEW를 관측했다. 독립 검토의 공용 예외 보존 결함 때문에 첫 시험을 중단했고 exit 2이므로 통과로 계산하지 않는다. 후속 원격 묶음 249 passed는 정상 종료했지만 착지 도구는 첫 중단 때문에 착지하지 않았다. 실패를 기존 실패 목록에 추가하지 않았다.
- gate 변화: 변경된 관측과 원격 재검사 준비다. Android proxy 회귀의 Windows 전용 실행 설정과 Linux SDK 부재는 별도로 해결한다.

## 2026-10-12 · e775bdd6a · Fleet 계정 진입점과 로그인 복귀 구현

- 변경: D-683을 선점하고 네 문서의 우측 로그인/계정과 전용 로그인 문서·허용 복귀 경로를 기존 쿠키 API에 연결했다. 로그인/로그아웃 readback, 중복 제출·비밀번호 초기화, Map/Cell 새 탭 로그인과 focus 재검증을 추가했다. 지도 재접속은 편집과 원래 revision을 보존하며 계획 권한을 다시 확인한다.
- 증거: 복귀 allowlist/공용 요청 Node39 PASS, JS 구문 확인. 독립 검토의 Cell credential·세션 만료·적용 전 지도 입력 보존 지적을 반영했다. 원격 Chromium·계약·최종 독립 재검토는 실행 전이며 배포 증거가 아니다.
- gate 변화: 소스 후보 단계. 기존 브랜치 G2/회귀는 새 인증 흐름 검증을 대신하지 않는다. 착지·push·배포·실물 수용 없음.
