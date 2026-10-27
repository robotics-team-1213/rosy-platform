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

## 2026-10-12 · 40b7937fa0 · D-671 기명 Discord 접수 source

- 변경: 기존 tasks DB의 별도 bounded 접수 원장, immutable Discord identity→현재 기명 operator, 전용 HMAC와 Goal/Cell producer 자격 격리, 같은 메시지 중복/수정 및 owner read를 구현했다. 순수 projection/signature holder는 Fleet wheel/sdist/source image에 함께 설치한다. Console 작업 화면은 자기 원문을 textContent로 읽고 권한 철회 시 지운다.
- 증거: 원격 RED 모듈 없음1 NEW, manifest 누락1 NEW 및 구조 증가1 NEW를 각각 수정했다. 최신 focused44 PASS/NEW0; 실제 Chromium4 PASS/NEW0(처음4 skipped는 pass 제외). 독립 source/Safety 검토 수용, Fleet53396/app906 재측정, +150/파일 상한/기존 추출 의무 유지. 실제 기명 HTTPS cookie 로그인은 별도 후속 증거에 기록했다.
- gate 변화: source 접수와 named Console 로그인 확인. Gateway/token/운영 identity mapping/실제 대화 수신 및 후보/승인/reply는 후속이다. Task/Mission/Job/claim/모델/장치 명령·push·image deploy는 없다. 근거: docs/validation/discord-fleet-pipeline-2026-10-12/named-login-and-intake.md.

## 2026-10-12 · b45e54d05a · D-680 요청 검토와 기존 Fleet 제출 화면

- 변경: 별도 channel-request-view owner가 원문 확인, 기명 검토, 보류/거절/이동 후보 저장을 담당한다. 실행 요청은 기존 confirmedAction/current safety gate와 Fleet goal API의 고정 request key를 재사용하고 기존 Task에 연결한다. textContent, 권한 철회 시 지우기와 LINKED 재제출 숨김을 보존한다.
- 증거: 실제 Chromium 320/1366과 viewer/operator 목록 6 PASS/NEW0. 취소 시 요청 없음, 저장 시 장치 요청 없음, 명시 확인 후 동일 request key/Task 연결을 검증했다. wheel/sdist 71개 자산 해시 readback과 allowlist 시험 통과. workflow-source.md 참조.
- gate 변화: source와 fake API의 실제 브라우저 경로만 검증했다. 최신 main 착지·독립 검토·CI·서명 배포·실제 Discord 왕복·장치/FIELD 수용은 후속이다.

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

## 2026-10-12 · cd42d880a · D-678 출발 준비 중 정지 안내

- 변경: TRIP_START_CANCELED에 한국어 운행 안내를 연결한다. 원시 오류 코드 대신 상태 확인 뒤 재시작을 안내한다.
- 증거: source 5f3f033a8의 원격 trip code label/취소/Task/goal 회귀 147 PASS, NEW 0; Node site-map 29 PASS. 서버와 물리 stop 권한은 바꾸지 않는다.
- gate 변화: SOURCE/호스트 회귀만 추가한다. 배포된 UI와 실제 운행 수용은 미확인이다.

## 2026-10-12 · 대화 요청 상태와 잠금 사유 보완

- 변경: 요청 검토 상태를 한국어로 표시하고 기존 workStatus를 재사용한다. 이동 후보 준비와 실행 준비를 구분하며 사건 인수·종료를 표시한다. 비활성 버튼·입력에는 기존 reason 및 aria-describedby 규약을 적용한다.
- 증거: source28650439cb 통합 원격 검사에서 enum 노출과 사유 없는 비활성 NEW2를 재현했다. Chromium 시험은 표시 문구와 사건 잠금 사유를 검증하도록 갱신했다. 수정 HEAD의 재검증은 후속이다.
- gate 변화: 실행·승인 권한 변화 없음. 배포·실제 Discord 왕복은 아직 미확인이다.

## 2026-10-12 · 193d54401 · 대화 요청 상태·잠금 사유 재검증

- 변경: 위 커밋된 제목 오류 기록을 보존하고 정식 후속 기록을 추가했다. 표시·접근성 보완은 기존 승인·안전 조건을 유지한다.
- 증거: source193d54401 AI PC 자원 하한을 충족한 원격 Chromium·문구·disabled·버전·설치·구조 전체 선택군 terminal exit0/NEW0, Node work-view2 PASS. 표시 문구와 사건 잠금 사유를 검증했다.
- gate 변화: source 회귀만 확인했다. 전체 영향 검사·착지·배포·실제 Discord 왕복은 미확인이다.

## 2026-10-12 · d3dac3633 · D-683 로그인·계정과 업무 복귀

- 변경: 네 문서 우측에 로그인/계정을 두고 `/console/login`에서 기존 쿠키 API로 인증한 뒤 서버 세션을 확인해 허용된 업무 주소로 복귀한다. 계정·화면 표시·고급 접속을 구분한다. 지도/Cell 새 탭 로그인, 로컬 편집 보존, 기존 revision 검사, 확인된 로그아웃/확인 불가를 구분한다.
- 증거: Console Node 312 PASS, 독립 소스 검토 추가 blocker 없음. 원격 `440385e24` 95 PASS / 1 NEW의 CSP 대기 helper를 수정하고 `0d01b320c` 재접속/편집 보존/충돌 최종 5 PASS, NEW 0을 확인했다. `06ce50c4a` Android proxy 실제 번들 브라우저 1 PASS와 JVM/assemble을 확인했다. 실패한 전체 묶음은 통과로 합산하지 않는다. 상세는 `docs/validation/all-ui-workflows-2026-10-12/result.md`.
- gate 변화: main 착지·push·CI·서명·설치·실물 수용 미확인. 시험 서버 캡처를 배포된 화면의 증거로 부르지 않는다.

## 2026-10-12 · 83c2a49fd · D-686 첫 변경과 D-689 내 프로필

- 변경: 초기 쿠키는 첫 비밀번호 변경에만 사용하고 네 운용 문서의 조작을 잠근다. 우상단 계정에서 본인 표시 이름/현재 비밀번호 확인 변경/읽기 전용 ID·이메일·권한을 관리한다. Map/Cell은 새 탭과 초안을 보존한다. 비밀번호/표시 이름 결과를 서버 재조회하며 만료·계정 전환은 비밀 삭제/제출 중단/명시적 재조회로 처리한다.
- 증거: 서버 73b23b956 원격 선택 173 PASS와 70e970acb Unicode 수정 20 PASS, 각각 NEW 0. UI/권한/소스의 독립 검토에서 찾은 오류를 수정했고 현재 통합 브라우저 시험은 별도 진행 중이다. 상세는 전체 UI 검증 결과 문서에 SHA/범위별로 기록한다.
- gate 변화: 최신 영향 gate·main 착지·push·CI·서명·설치·팀원 발급과 실제 첫 변경은 미확인이다. 기존 서비스 자격과 CORE 최종 명령 권한을 유지한다.


## 2026-10-12 · d002c579d · D-689 계정 화면 용어 정렬

- 변경: 기본 프로필 기능의 화면 이름과 우상단 링크를 내 계정으로 통일하여 운용 용어 규칙을 지킨다. URL과 본인 정보 관리 동작은 유지한다.
- 증거: d002c579d 전체 영향 원격 첫 묶음 6921 PASS/800 SKIP/2 NEW, 둘째 묶음 537 PASS/309 SKIP/1 NEW를 확인했다. 용어·API 버전·합친 계획의 공개 commit 표기 문제를 재현했으며 각각 known_failures NEW 2/1이다. 수정 재검증 대기다.
- gate 변화: 없음. 착지·배포·팀원 발급은 미확인이다.

## 2026-10-12 · 99b25e23e · D-685 최소 사람 개입과 학습 원본

- 변경: 승인된 Fleet 범위에서 WAIT/YIELDED 재관측 복구·동일 사건 예산·durable UNKNOWN no replay·검증된 trip 재계획을 연결했다. 상태/센서 원장, read_guard cursor 조회, 해시 재검증되는 비라벨 학습 source export와 통합 규칙집을 추가했다.
- 증거: 관련 원격 238 passed/NEW 0, Node 52 passed, pipeline_review 독립 소스 검토 완료. 최신 main 통합 원격 5262 passed/252 skipped에서 8 NEW를 발견해 착지를 중단하고 호출자/fixture/layer/크기/공개 commit 표기를 수정했다. 최종 gate는 후속 실행 로그로 확인한다.
- gate 변화: SOURCE 구현 증거. CI·push·배포·현장 autonomous opt-in·물리 무인 수용·실제 학습/승격은 미확인. 센서 원본/불명/결측을 정답으로 만들지 않는다.

## 2026-10-12 · f3ba7590c · Discord 확인의 기명 계정 전환 경계

- 변경: 같은 operator 역할의 principal이 바뀌어도 기존 확인과 대화 요청 선택을 초기화한다. 기존 확인 owner는 token·role·locked에 더해 principal도 확인한다. 초기 비밀번호·본인 프로필과 Cell 서비스 부재 계약을 함께 보존했다.
- 증거: 원격 실제 Chromium의 기존 사건 확인 시험 두 화면에서 같은 역할의 bob→alice 전환 후 확인창이 남는 NEW2를 재현했다. 수정 버전의 GREEN·설치76개·구조 검증은 후속이다.
- gate 변화: 실행 권한 확대 없음. CI·서명 배포·실제 Discord 왕복은 미확인이다.

## 2026-10-12 · 438e6256a · 계정 전환 시험의 수명 조건 정정

- 변경: Chromium 계정 전환 시험에 실제 pagehide→pageshow 순서를 적용했다. 이전 pageshow 단독 시험은 인증 재조회가 발생하지 않아 제품 결함 재현 증거로 사용할 수 없다. 기존 scope가 이전 응답을 차단하므로 추가 공통 호출 guard는 만들지 않았다.
- 증거: 독립 검토가 실제 모든 refreshAuthorization 호출 경로의 기존 scope 무효화를 확인하고 앞선 blocker를 철회했다. 두 줄 principal 방어 보강은 source/Safety 승인했다. 기존 확인 owner의 pending principal 교체는 별도 Node 회귀로 검증한다.
- gate 변화: 앞선 NEW2는 잘못된 lifecycle fixture의 실패로 정정한다. 원격 GREEN·설치·착지·운영 검증은 후속이다.

## 2026-10-12 · 5941920df7 · D-720 원문 요청의 숙고 상태 표시
- 변경: 기존 요청 검토 상태에 bound 모델 ID·숙고 상태·실행 승인 아님을 표시한다. owner 결과 조회 실패도 상태가 성공한 것으로 표시하지 않는다.
- 증거: source scoped review 승인. 실제 브라우저/서명 배포·Discord 왕복은 별도 후속 검증이다.
- gate 변화: source 연결. 접수·판단·장치 실행·목표 완료는 서로 다른 수용이다.

## 2026-10-12 · e7ada4b52 · D-668 Fleet header controls

- 변경: 공용 테마 순환과 접속·알림 진입점을 구현했다. 권한 예외와 요약 열기/읽음의 구별을 유지하고 Escape 포커스를 제공한다.
- 검증: 첫 구현의 원격 정적·권한·토큰·Node·구조 검사 103건과 Chromium 25건이 통과했으나, 사용자 검토에서 상태 표지의 의미와 묶음이 불명확해 거절됐다. 스킬 기반 의미·배치 평가 후 상태 센터의 한 누름 영역으로 재구성한다. 첫 구현의 통과를 최종 디자인 수용으로 보지 않는다.
- gate 변화: 기존 게이트는 유지한다. 수정된 디자인의 원격 회귀·CI·서명 설치는 별도 검증하며 장치 명령은 시험하지 않았다.

## 2026-10-13 · cfeced643 · main 브라우저 회귀 수정 (D-683/D-493/D-519)

- 변경: 세션이 있으면 헤더 `로그인` 링크를 숨긴다(`#fleet-login`의 ID 규칙이 `[hidden]`을 이겼다, D-683 1). 지도 칸이 천장 프레임을 나눠 보이는 동안 오른쪽 열 썸네일을 접는다(D-493 3). 점유 격자의 원점 글자를 겹침 선 뒤에 칠한다(US-009). 세션 시험은 첫 토큰 입력 전에 `토큰으로 접속` 접힘을 연다(D-519 6, D-658 6). DESIGN.md의 Fleet 헤더 문구를 D-668·D-683에 맞췄다.
- 증거: main 5feb00b2e를 모델 PC Chromium으로 돌려 Fleet 21개 파일 382 passed 6 failed, 그 밖 36개 파일 659 passed 2 failed(`X:/DevTemp/land-recent/browser/1/`). 이 브랜치의 재실행은 하지 못했다. 15:00부터 노트북 Tailscale이 다른 tailnet 계정으로 바뀌어 모델 PC·현장 PC에 닿지 않았다. `node --check map-view.js` 통과, harness lint 0 error.
- gate 변화: 없음. 수정 4건은 원격 Chromium 확인 전이라 착지 근거가 아니다. Learning `test_learning_summary_separates_review_from_training`과 Games `test_compact_board_recovery…[320-568]` 실패는 원인 확인 전이다.

## 2026-10-13 · 7f40561e6 · main 브라우저 회귀 수정 재확인 (D-683/D-493/D-519)

- 변경: 세션이 있으면 헤더 `로그인` 링크를 숨긴다(`#fleet-login`의 ID 규칙이 `[hidden]`을 이겼다, D-683 1). 지도 칸이 천장 프레임을 나눠 보이는 동안 오른쪽 열 썸네일을 접는다(D-493 3). 점유 격자의 원점 글자를 겹침 선 뒤에 칠한다(US-009). 세션 시험은 첫 토큰 입력 전에 `토큰으로 접속` 접힘을 연다(D-519 6, D-658 6). 시험 경합 세 곳을 고쳤다: 지워진 툴팁 주인 옆 버튼의 설명, lease route 수, 다시 그려지는 로봇 카드 스크롤. DESIGN.md의 Fleet 헤더 문구를 D-668·D-683에 맞췄다.
- 증거: 모델 PC Chromium. 고치기 전 main 5feb00b2e는 Fleet 21개 파일 382 passed 6 failed, 그 밖 36개 파일 659 passed 2 failed. 이 브랜치는 Fleet 388 passed(7f40561e6), 그 밖 683 passed(3f32f2888, 이후 커밋은 Fleet 시험 두 파일만 바꿨다), skip 0. 원격 pytest(8cae1dece): `operations/fleet/test`, `shared/web/test`, harness·구조 가드 모두 exit 0, known_failures NEW 0. harness lint 0 error. 로그 `X:/DevTemp/land-recent/browser/`.
- gate 변화: 없음. 소스 브라우저 회귀만 확인했다. 착지·push·CI·설치본·실물은 별도다. Games `test_compact_board_recovery…[320-568]`은 첫 전체 실행에서 한 번 실패한 뒤 단독 10회와 전체 2회에서 통과했고 원인은 찾지 못했다.

## 2026-10-13 · 1438d53d1 · feat(web): control line (D-741), Cell 묶음 선 유지

- 변경: `cell/cell.css`의 `.document-group` 테두리를 `--field-line`에서 `--border-default`로 옮겼다. `--field-line`이 조작 경계(잉크 50%)가 되어도 폼 묶음 선은 면 구분으로 남는다. `.file-picker-button`은 조작이라 `--field-line`을 그대로 쓴다.
- 증거: 원격 소스 시험 통과. 화면 확인 없음.
- gate 변화: 없음.

## 2026-10-13 · 9e2d4ef0c · feat(fleet): one-row app bar and named rail (D-741 조각 4·5)

- 변경: 네 문서의 머리가 맥락 | 연결 | 알림·나 | 정지의 한 줄 앱 바가 됐다. 시계와 연결 글(`실시간`·`지연`·`연결 끊김`)이 머리로 오고 푸터와 그 안의 `관제 알림` 링크가 없어졌다. 알림 단추는 정적 마크업이다. 계정 단추(`#topbar-more`)가 역할 이름을 달고 그 아래에 계정·화면 표시·토큰 접속이 있다. 로봇 연결 수(`#online-pill`)는 관제 문서의 지도 머리로 갔고 다른 세 문서에는 없다. 레일 아이콘 아래에 `관제·설치·지도·작업·Cell`을 적었다. 접힘은 `.fleet-shell` 칸 질의(64rem, 48rem, 30rem)다.
- 증거: 원격 소스 시험과 node 단위 시험 통과, `known_failures` NEW 0. `*_browser.py`는 원격에서 돌지 않았다. `operations/fleet/test`의 브라우저 시험은 푸시 뒤 CI가 증거이고, `test/test_fleet_console_browser.py`와 `shared/web/test/test_theme_browser.py`는 어디서도 저절로 돌지 않는다.
- gate 변화: 없음. D-153 G2 캡처와 G3 사람 검토는 `docs/validation/fleet-app-bar-2026-10-13.md`에 적은 대로 아직 없다.

## 2026-10-14 · 390f2c6de · feat(fleet): five areas, sub-nav seat, work and records areas (D-741 조각 6·7·8)

- 변경: 네 문서의 레일이 `관제·작업·기록·지도·설치` 다섯 영역이 됐다. 현장 지도와 Cell의 가로 앵커 줄(`.task-nav`)이 공용 하위 탐색 자리(`/common/app-shell.css`의 `.ui-subnav`)로 갔다. `/console?view=work`는 `전체 작업·승인 대기·끝난 작업·새 작업`을, `/console?view=records`는 `검토할 사건·열린 사건·닫힌 사건·AI 상황 사실·관제 기록`을 하위 탐색에 둔다. 화면은 `show`로 고르고 기존 `GET /api/fleet/work`, `GET /api/fleet/incidents` 답을 브라우저에서 거른다. `/console/cell`은 주소를 유지하고 `작업` 영역의 `새 작업`이다. 기록 영역에서는 사건 패널(또는 관제 기록)이 본문으로 올라가고 연 사건의 담당 인수·사람 검토·검토 폼이 오른쪽 칸 `원인과 조치`에 선다. 관제의 `기록·근거` 탭은 그대로다.
- 증거: 원격 소스 시험 통과(`known_failures` NEW 0). 브라우저 시험은 시험 PC에서 조각마다 돌렸고 결과는 착지 보고에 있다. 화면을 사람이 본 적은 없다.
- gate 변화: 없음. 검토 반영(2376c3886: 자리의 사건 이름, 한 번에 한 건을 스크립트로, 키·스크롤·상한 표기) 뒤 Fleet 크기 단위가 55464로 상한 55452를 12줄 넘었다. 판정은 올리지 않고, 저장소 어디서도 부르지 않는 Fleet 서버 코드 33줄(쓰지 않는 import 8, `mark_rejected`, `next_running`, `next_reconciliation`, `_ACTOR`, `formation_relay_kwargs`, `anchor_status`)을 지워 55439가 됐다(D-168). D-153 G2 캡처와 G3 사람 검토는 없다.

## 2026-10-14 · 2c409d117 · refactor: console.js의 읽지 않는 선언 두 개 삭제

- 변경: `console.js`의 `authHeaders()`와 `lastStateOk`를 지웠다(5줄). 둘 다 선언만 있고 읽는 곳이 없다. `install.js`의 `authHeaders`는 그대로다.
- 증거: `node --check console.js`, `operations/fleet/test/web` node 시험. 원격 시험 결과는 이 브랜치의 최종 보고에 적는다.
- gate 변화: 없음.

## 2026-10-14 · 33f6d8415 · fix(fleet): 현장 지도·Cell의 열이 본문 폭에 답한다 (D-741 2)

- 변경: `site-map.css`와 `cell/cell.css`의 `main`이 칸(`container-type: inline-size`)이 됐고 64rem 접힘이 `@media`에서 `@container`로 갔다. 레일 72px과 하위 탐색 232px 옆에서 넓은 배치는 본문 자체가 64rem일 때부터 선다. 30rem 전화 단 규칙은 뷰포트 그대로다. 머리와 비상 정지는 건드리지 않았다.
- 증거: 고치기 전 측정(모델 PC Chromium, `X:/DevTemp/browser-run/snw-measure-fleet-1.txt`): 1024×768에서 본문 720px, 두 열이 336px씩, 세 열 폼의 칸 104px(1100에서 117px). 하위 탐색이 들어오기 전 같은 시트의 64rem 경계 값은 계산으로 154px다(잰 값이 아니다). 가로 넘침·가려진 하위 탐색 항목·잘린 단추 글은 없었고 Cell 하위 탐색의 아래 끝은 651px다. 고친 뒤(`snw-measure-fleet-2.txt`, sha 71e43aeed): 1024와 1100에서 한 열, 폼 칸 221px 이상, 1366에서는 전과 같은 두 열(칸 161px). 관련 브라우저 파일 넷 162 passed(`snw-fleet-files-1.txt`). 원격 소스 시험 known_failures NEW 0.
- gate 변화: 없음. Fleet 크기 단위 56742 → 56744(기준 56755). 창 높이가 651px보다 낮은 넓은 창에서 Cell 하위 탐색의 아래 항목이 화면 밖에 남는지는 재지 않았다. Cell `요청 키` 입력은 1024에서 값(311px)이 칸(219px)보다 길어 입력 안에서 밀어 읽는다.

## 2026-10-14 · ac505f819 · test(fleet): 기록 영역을 320×568·밝게·1024에서 잼 (D-741 8)

- 변경: 제품은 그대로다. `test_records_area_fits_the_narrowest_phone_and_reads_in_the_light_theme`이 가로 넘침, 비상 정지(화면 안, 위에 덮인 것 없음), 하위 탐색 다섯 항목, 판단 자리의 제목과 검토 폼(창 안, 잘리지 않음, 서로 겹치지 않음), 기록 자리 글의 대비를 잰다.
- 증거: AI PC Chromium 6 passed(`X:/DevTemp/browser-run/snw-measure-records-3.txt`, sha ac505f819): 320×568 어둡게·밝게, 390×844 밝게, 1366×768 밝게, 1024×768 어둡게, 1100×800 밝게. 넘침 0, 글 45~47개 가운데 4.5:1 아래 없음, 320에서 폼 칸 296px, 1024에서 판단 자리 219px. 결함은 찾지 못했다.
- gate 변화: 없음. 1024에서 `console.js`는 아직 뷰포트 폭으로 본문을 2:1로 나눠 판단 자리가 219px다(1366에서 333px). 쓸 수는 있어 고치지 않았다. 화면을 사람이 본 적은 없다.

## 2026-10-14 · 8b44b2399 · test(fleet): 폭마다 열 수를 고정하고 360·1349를 더함 (검토 반영)

- 변경: 제품은 그대로다. 현장 지도와 Cell 본문 시험이 폭마다 기대하는 열 수를 그대로 단언한다. 앞 시험의 `열 1 또는 칸 144px 이상`은 1024와 1100에서 실패할 수 없었고, 보이는 자식이 없는 격자는 `Infinity`로 통과했다. 그런 격자는 재지 않는다. 여러 열일 때의 9rem 바닥은 남겼다. 창 밖으로 나간 조작도 잰다. 기록 영역 시험은 밝게일 때 `body` 바탕이 어둡게와 다른지 먼저 본다.
- 증거: 모델 PC Chromium 16 passed(`X:/DevTemp/browser-run/snw-review-fleet-1.txt`, sha 8b44b2399), 세 파일 전체 165 passed(`snw-review-fleet-files-1.txt`). 넓은 배치가 서는 실제 범위: 앞 항목(33f6d8415)의 "1366에서는 두 열"은 셸 폭이 1366일 때의 값이다. 넓은 배치는 `main`의 내용 폭이 64rem일 때, 곧 셸 폭(창 폭에서 세로 스크롤바를 뺀 값) 1360px부터 선다. 1024px 이상 1360px 미만의 셸은 모두 한 열이다. 1349(스크롤바 17px가 있는 1366 노트북 창)에서 쟀다: 본문 1045px, `main` 내용 1013px, 한 열, 현장 지도 폼 칸 1013px, Cell 칸 세 열 330px. 고치기 전 그 창은 두 열이었다(칸 계산값 약 158px). 360에서 쟀다: 한 열 328px, 가로 넘침 0, 잘리거나 창 밖으로 나간 조작 없음. 두 문서의 `main` 안에는 공용 22rem 칸 부품(`.ui-form`·`.ui-readout`·`ui-actions`)이 없다.
- gate 변화: 없음. 스크롤바가 자리를 차지하는 1366 노트북 창에서 두 문서가 한 열이 되는 것은 이 브랜치가 만든 변화다. 접히는 값을 낮출지는 정하지 않았다. 머리 없는 Chromium은 스크롤바 폭을 잡지 않아 1349는 뷰포트 폭으로 흉내 냈다.

## 2026-10-14 · 08fd296c0 · fix(fleet): 현장 지도·Cell 본문 접힘을 60rem으로 (D-741 2)

- 변경: `site-map.css`와 `cell/cell.css`의 칸 질의 접힘을 64rem에서 60rem으로 내렸다. 64rem이면 스크롤바가 있는 1366 노트북 창(셸 1349px, `main` 내용 1013px)이 한 열이 되어 폼 칸 하나가 1013px였다. 고치려던 것은 1024·1100 창의 104~117px 칸뿐이다. 60rem은 세 단 값이 아니라 `shared/web/surfaces.yaml`의 `console` 표면 `container_breakpoints`에 이유와 함께 올렸다. 앞 항목(8b44b2399)의 "셸 1360px부터 넓은 배치"는 이 커밋으로 바뀐다.
- 증거: 실제 범위 — 넓은 배치는 `main` 내용 폭 960px, 곧 셸 폭(창 폭에서 세로 스크롤바를 뺀 값) 1296px부터 선다. 셸 1024px 이상 1296px 미만은 한 열이다. AI PC Chromium 10 passed(`X:/DevTemp/browser-run/snw-fold60-measure-1.txt`, sha 08fd296c0): 1024는 한 열(본문 내용 688px, Cell 칸 221px), 1100은 한 열(764px, 247px), 1349는 두 열(열 499px, 세 열 폼 칸 158px), 1366은 두 열(열 507px, 칸 161px), 360은 한 열 328px. 모든 폭에서 가로 넘침 0, 잘린 단추·선택 글 없음, 지도 글자 높이 14px. 두 열이 서는 가장 좁은 셸 1296px의 칸은 계산으로 149px다(잰 값이 아니다). 세 브라우저 파일 전체와 원격 소스 시험 결과는 착지 보고에 있다.
- gate 변화: 없음. Fleet 크기 단위는 56744 그대로다. 머리 없는 Chromium은 스크롤바 폭을 잡지 않아 1349는 뷰포트 폭으로 흉내 냈다. 화면을 사람이 본 적은 없다.

## 2026-10-14 · 41a19818e · feat(fleet): 규칙 M 경고 행과 카드 표시 (D-550 8항, D-760 3항 1단계)

- 변경: `queues.js` `attentionItems`가 `robot.rule_m.state === "unbounded"`일 때 주의 행 하나(`: 한도 없는 움직임 — 관제가 끊겨도 로봇이 계속 갑니다 (<이유>)`)를 낸다. `roster.js` 카드는 연결 태그 자리 옆에 `한도 없음` 태그를 붙인다. 이유 글은 `link-tag.js` `ruleMTag` 한 곳에 있다. 새 칸·새 클래스·인라인 스타일은 없다.
- 증거: `node --test`(link-tag, attention-stale, queue-inline) 통과, `test_console_queues_contract.py` 원격 통과. 브라우저 시험과 화면 확인 없음.
- gate 변화: 없음.

## 2026-10-14 · ba11d856d · fix(fleet): 규칙 M 카드 글과 이유 정리 (검토 반영)

- 변경: 카드 태그 글을 `정지 한도 없음`으로 바꿨다. 이유는 `hold_back`·`no_goal_lease`·`leg_unknown` 셋이다. `ruleMTag`의 쓰지 않는 `reason` 값과 카드의 `data-rule-m`을 지웠다. 오프라인 로봇은 서버가 판정을 주지 않아 주의 행도 카드 태그도 없다.
- 증거: `node --test`(link-tag, attention-stale, queue-inline) 통과. 브라우저 시험과 화면 확인 없음.
- gate 변화: 없음.

## 2026-10-14 · 776bdacfc · feat(fleet): 새 작업에 이동 종류 (D-763 조각 3)

- 변경: 작업 › 새 작업은 `/console?view=work&show=new`의 종류 목록이다. 이동은 활성 현장 지도에 장소가 있고 로봇이 있을 때만 선다(꺼진 단추가 아니라 없는 항목, D-763 9). 누르면 오른쪽 칸에 로봇 선택과 로봇 카드의 운행 폼(`card-trip.js` `trip.section`, `focus`)이 선다. 계획·시작은 카드와 같은 `planTrip`/`startTrip`이고 거절 글도 같다. 서버 변경 없음. Cell 적재는 `/console/cell`로 가고 그 문서의 하위 탐색 `새 작업`이 새 주소를 현재로 표시한다. Cell 문서의 `#work-kind` 문장과 작업 상세의 `팔 공정 설정` 링크를 지웠다. `placeOptions`를 내보낸다.
- 증거: 원격 소스·node(`test_site_map_api.py`의 `node --test` 포함) 145 passed(HEAD 229d47e94, 모델 PC; 같은 이름 로그가 다음 실행에 덮였다), `known_failures` 0 new. AI PC Chromium 39 passed(`X:/DevTemp/browser-run/work-move-b1.txt`, nonce 2026-10-14_19:16:26, sha 229d47e94): 카드와 새 작업에서 보낸 요청 넷(계획·시작·계획·바쁜 시작)이 method·path·body·content-type까지 같고 `TRIP_ROBOT_BUSY` 거절 글이 같다. 장소 없는 지도에서 이동 항목이 없고 생기면 선다. 1366·390에서 가로 넘침 없고 비상 정지가 첫 화면에 있다.
- gate 변화: 없음. 장치에서 새 작업으로 시작한 운행 한 번이 카드와 같은 trip 기록을 남기는지는 확인 못 함. 화면을 사람이 본 적은 없다.

## 2026-10-14 · 13b907495 · test(arch): 관제를 자기 크기 단위로 (D-763 조각 3, D-753)

- 변경: `site_ui/console`을 `SIZE_UNITS`에 더했다(첫 등록 229d47e94, 이 커밋이 재판정 조건 반영). D-757 판정 커밋 61aa49b32에서 잰 값으로 나눈다: 서버 `fleet` 38822 + 관제 17933 = 56755. 브랜치 기점 06e97383b까지의 101줄(서버 +46, 관제 +55)은 다시 잡지 않는다. 지금 서버 38868, 관제 18023. 계획 `docs/plans/2026-10-14-fleet-console-size-unit.md`.
- 증거: 읽기 전용 critic 독립 재판정 AGREE-WITH-CONDITIONS, 조건 반영. 원격 AI PC `test_module_structure.py`(P6 셋 포함)·`test_doc_tabs.py`·`test_site_map_api.py` 70 passed(`X:/DevTemp/work-move/run-1.txt`, HEAD 13b907495), `known_failures` 0 new.
- gate 변화: 없음.

## 2026-10-14 · f38a5093a · feat(console): 카드에 trip 기다림, 상한을 넘으면 개입 행 (D-763 조각 2, API v1.231)

- 변경: `shared/site-map-model.js` `tripWaitText`가 `대기 · 횡단보도`·`대기 · 신호`·`대기 · 통행권`·`대기 · 연결`(상한을 넘으면 `대기 상한 넘음 · …`)을 만든다. `card-trip.js` 카드 줄은 기다림이면 이것을 먼저 보인다. `queues.js`는 `wait.over_bound`인 열린 trip을 crit 행 `개입 필요 — 대기 상한 넘음 · …`으로 낸다. 지도 화면 trip 줄(`tripStatusText`)에도 같은 글. API 문서 v1.231과 버전 고정 시험.
- 증거: 원격 시험(모델 PC) 284 passed(node 시험 포함), 로그 X: `wait-read/run-1.txt`. 브라우저(모델 PC, f38a5093a) `test_console_card_trips_browser.py` 20 passed: 카드 글, 1366×600·390×844 넘침 없음, 비상 정지 화면 안, 상한 넘으면 최우선 개입 행. 로그 X: `browser-run/wait-read-b1.txt`.
- gate 변화: 없음.

## 2026-10-14 · 7c26a028c · fix(console): 상한을 넘은 기다림은 주의 행 (D-763 개정 2 질문 7)

- 변경: 상한을 넘으면 카드 줄과 주의 행이 `대기 상한 넘음 · 막힘 해결 중 · <사유>`다(warn). crit `개입 필요` 행을 지웠다. 개입은 기존 막힘·해결기 인계 경로가 낸다.
- 증거: 원격 시험(AI PC) 285 passed(node 시험 포함), 로그 X: `wait-read/run-1.txt`. 브라우저(AI PC, 7c26a028c) `test_console_card_trips_browser.py` 20 passed: 상한 넘으면 주의 목록과 카드 줄에 글, 최우선 개입 목록에는 없음. 로그 X: `browser-run/wait-read-b2.txt`.
- gate 변화: 없음.

## 2026-10-14 · f79947c25 · fix(console): 지도 화면 trip 줄은 열린 trip에만 기다림 글

- 변경: `tripStatusText`가 `started`·`running`·`link_wait` trip에만 `tripWaitText`를 붙인다. API로 취소된 trip은 저장된 마지막 `waiting: true`를 가지고 있을 수 있다. `site-map-model.js` 799줄 그대로. 0d66d8b41에서 상한 넘김 글을 중립 문구 `대기 상한 넘음 · <사유>`로 바꿨다.
- 증거: node 시험 포함 원격 218 passed, 로그 X: `wait-read/run-1.txt`. 브라우저(AI PC, f79947c25) `test_console_card_trips_browser.py` 20 passed, 로그 X: `browser-run/wait-read-b5.txt`.
- gate 변화: 없음.

## 2026-10-14 · ce31980a5 · feat(console): 작업 칸에서 승인 대기 팔 작업 승인 (D-741 7)

- 변경: `/console?view=work`에서 `PROPOSED` 팔 작업(Mission)을 고르면 오른쪽 작업 칸에 `실행 승인`(`#work-admit`)이 선다. Cell과 같은 기존 `POST /api/fleet/missions/{id}/admit`에 `/api/fleet/dispatch-control`의 `generation`을 `expected_generation`으로 보낸다. 보기 전용이면 `운영자 권한이 필요합니다`, 공유 토큰이면 `이름 있는 운영자 로그인이 필요합니다`를 단추 아래 사유로 적고 막는다(세션의 역할·주체에서 나온다). 그 밖의 거절은 서버가 답한 말을 그 자리에 적고, 5xx·연결 실패는 결과 미확인으로 적고 다시 보내지 않는다. 성공하면 목록과 칸을 다시 읽는다. 새 API·필드는 없다.
- 하지 않은 것: `반려`는 없다. `PROPOSED` 작업을 반려하는 서버 경로가 없다(Cell `cancel`은 `PROPOSED`를 거절하고, Mission에는 취소 경로가 없다). Cell 작업은 `/api/fleet/work`에 나오지 않아(`fleet_cell_jobs`는 이 조회에 없다) 제안자 규칙과 `적재 배치 미리보기 열기`는 이 목록에 설 자리가 없다. 서버가 그 규칙으로 거절하면 그 코드가 사유로 보인다.
- 증거: 브라우저 시험 `test_pending_seat_approves_through_the_existing_admit_route`(1366·390 × 승인·보기 전용·공유 토큰·거절·미확인)를 포함한 `test_work_overview_browser.py` 20 passed, AI PC Chromium(`X:/DevTemp/browser-run/work-approval-b4.txt`, sha 226268b05). 첫 실행에서 `ui-button`이 `hidden`을 무시해 단추가 늘 보이고, 서버 코드가 든 사유가 1366에서 단추를 넘치게 한 것을 잡아 226268b05에서 기존 규칙(`#dispatch-rearm[hidden]`, `.work-list ui-button`)에 이름을 더해 고쳤다. 화면을 사람이 본 적은 없다.
- gate 변화: Fleet 크기 단위 +25줄. D-753 증가 허용 0을 넘는다. 지울 수 있는 죽은 코드(`next_running_mission` 등)는 main에서 이미 지워졌다.

## 2026-10-15 · 6ae1df74e · D-763 조각 4: 작업 화면의 trip·Cell Job 행과 서버 종류 목록

- 변경: `work-view.js` 줄 글이 서버의 보이는 상태를 쓰고 기다림을 먼저 보인다(`tripWaitText`, 상한을 넘으면 `대기 상한 넘음 · <사유>`, 개입 아님). 필터에 운행·Cell 적재, 끝난 작업에 trip 끝 상태. trip·Cell Job 행은 기존 상세 읽기를 연다. 새 작업은 `/api/fleet/work`의 `kinds`에 있는 종류만 보이고 답이 없으면 아무 종류도 없다. `console.js` `paintMove`의 브라우저 추측(장소·로봇) 줄을 지웠다. 콘솔 단위 18082→18083(상한 18083).
- 증거: 브라우저(AI PC, 6ae1df74e) `test_work_overview_browser.py`·`test_console_card_trips_browser.py` 35 passed, 로그 X: `browser-run/wrs4-b1.txt`. node 시험은 `test_site_map_api.py`로 원격 225 passed 안에 있다.
- gate 변화: 없음.

## 2026-10-15 · e7b196839 · D-763 조각 4 검토: 끝난 작업·승인 대기는 보이는 상태로 거른다

- 변경: `work/work-view.js`(6377fe873에서 `work/`로 옮김, 자기 크기 단위)의 `show=pending|done`이 서버의 `visible_state`(`approval_pending`·`ended`)로 거른다. 취소된 Cell Job은 끝난 작업에 있고 실패한 Task는 없다. 6ae1df74e에서 크기를 맞추려고 한 줄에 모은 문장을 파일의 모양으로 되돌렸다. 단위: 콘솔 17,717/17,719, 작업 영역 379/514.
- 증거: 브라우저(AI PC, e7b196839) `test_work_overview_browser.py`·`test_console_card_trips_browser.py`·`test_cell_app_browser.py` 93 passed, 로그 X: `browser-run/wrs4-b3.txt`.
- gate 변화: 없음.

## 2026-10-15 · 239d2d607 · D-767 P0 로봇 카드 "예고" 한 줄

- 변경: `shared/site-map-model.js` `trafficCardLine`이 `/traffic` 행의 `preview` 첫 두 사건을 "예고: 0.42 m 왼쪽 회전 · 0.95 m 횡단보도"로 붙인다. 없거나 만료한 미리보기는 서버가 행에서 빼므로 아무것도 안 보인다. 파일 800/800, 콘솔 단위 17,718/17,719.
- 증거: `operations/fleet/test/web/traffic-layer.test.mjs`(원격 `test_site_map_api.py` node 시험 포함 fleet 5,290 passed). 브라우저는 확인 못 함.
- gate 변화: 없음.


## 2026-10-16 · uncommitted · 앱별 작업으로 이동하는 로봇 카드

- 변경: 승인 directory에서 Robot/Pilot 링크를 구성하고 주소가 없거나 충돌하면 안내한다. 새 원장·명령·URL 토큰 전달을 추가하지 않는다. 세션·화면 수명 변경에서 캐시를 폐기하는 회귀를 검증한다.
- 증거: `docs/validation/app-role-clarity-2026-10-16/result.md`. 최종 리뷰 회귀와 affected 시험은 실행 기록에서 확인한다.
- gate 변화: 없음. main 착지·push·배포·새 DEVICE/FIELD 시험 없음.

## 2026-10-17 · a49062a0e · D-775 실측 교정의 목적별 운영 연결

- 변경: versioned 수치 bundle, Fleet preview 승인·영속 CAS·감사·철회, source config와 수치 readback, 촬영 session/epoch에 결속한 Vision render, Console 승인·재확인·철회 흐름을 연결했다. 기존 tracking/sighting/World/CORE 권한은 유지한다.
- 증거: 검증 행렬은 docs/validation/measured-camera-lifecycle-2026-10-16/result.md. d4744b1758에서 공유 계약·Vision와 실제 Fleet→Vision 통합 1,610 passed; 1a9efa0baa UI/설치/공용 계약 79 passed; b367260187 provenance/비밀 경계/통합 128 passed. 광범위 회귀에서 발견한 fixture 의존 경로와 정확한 CSS 목록도 보완했으며 최종 범위 결과를 별도 기록한다.
- gate 변화: 코드·원격 합성·브라우저 범위. 실제 촬영·독립 측량·ARM64·설치·DEVICE/FIELD와 D-598 운영 주행 수용은 미검증. main 착지·push·배포 없음.

## 2026-10-17 · 8c6692128 · 설치 보정 손잡이의 상단 바 가림 수정

- 변경: 실측 교정 패널로 늘어난 화면에서 기존 사각 보정 손잡이를 스크롤하면 고정 상단 바에 가려졌다. 손잡이의 스크롤 시작 여백에 공용 앱 바 높이와 간격 토큰을 적용했다.
- 증거: 병합 전 전체 원격 검사 ea71743778의 `test_camera_rectification_direct_manipulation`이 실제 hit test에서 실패했다. 8c6692128의 같은 드래그 검사와 실측 교정 브라우저 두 폭은 3 passed, NEW 0이다. 원본 로그는 저장소 밖 `C:/DevTemp/camera-calibration/landing-handle-fix/`에 있다.
- gate 변화: 없음. 수정본과 최신 main의 전체 병합 검증은 별도 수행한다.

## 2026-10-17 · uncommitted · 실측 보정 조회와 승인 동시 실행 차단

- 변경: 실측 보정 상태 조회 중 승인·확인·철회·영상 읽기를 잠그고, 이벤트 처리에서도 조회와 쓰기가 겹치지 않게 했다. source·session·revision 확인과 미리보기 만료는 유지한다.
- 증거: FULL 통과 뒤 main 추가 변경 검사에서 미리보기 표시 1건이 실패했다. 기존 브라우저 흐름에서 상태 응답을 보류하는 재현 검사를 추가했고 commit `1cde86ca1`의 데스크톱·전화 폭 모두 조회 중 확인 버튼이 활성 상태로 남아 실패했다. 수정본의 원격 재검증은 후속이다.
- gate 변화: 없음. 실패를 기준선에 추가하지 않았으며 main 착지·push·배포·실측·DEVICE/FIELD 수용으로 표시하지 않는다.

## 2026-10-17 · uncommitted · 실측 보정 조회 중 입력 유지

- 변경: 자동 상태 조회 중 로컬 파일·오차 한도·촬영 조건 입력은 유지하고, 승인·확인·철회·영상 읽기 요청은 계속 잠근다. 조회와 쓰기의 동시 실행 차단과 실제 session·revision 변경 시 조건 해제는 유지한다.
- 증거: commit `8e72b84d65`의 FULL 일반 22묶음과 브라우저 216·211건은 통과했으나, 보정 확인란 클릭 1건이 실패해 착지하지 않았다. commit `11729e090`에서 실제 mouse down/up 사이에 상태 응답을 보류한 재현 검사는 두 폭 모두 확인란이 선택되지 않아 실패했다. 수정본 검증은 후속이다.
- gate 변화: 없음. 실패 원본과 중단 상태를 외부 기록에 보존하며 실패 목록을 늘리지 않는다.

## 2026-10-18 · uncommitted · D-801 관제 콘솔 로봇 영상(사이트 발급 읽기 위임)

- 변경: `shared/robot-video.js` 패널이 로봇별 위임으로 타일마다 WHEP를 재생한다(최대 6). 숨김 시 세션 종료, 실패 타일은 영상 없음.
- 증거: 원격 시험 결과는 착지 기록에 남긴다. 장치·현장 측정은 2026-10-18 사용자 결정으로 생략했다.
- gate 변화: 없음. 모자이크(MCU)는 후속 feat/site-video-mosaic이다.

## 2026-10-19 · uncommitted · D-806 앱 표시 이름과 현재 역할 정합

- 변경: Fleet 하위 화면 제목을 Rosy Fleet — 화면으로 맞추고 계정 관리의 앱 이름은 Fleet으로 표시했다. Cell의 역할은 팔레타이징 작업 준비이며 제안과 별도 실행 승인 경로는 유지한다.
- 증거: 제목 회귀 검사의 수정 전 원격 실행은 2 failed로 기존 불일치를 확인했다. 수정 후 검증은 이 작업의 커밋과 외부 시험 기록으로 확인한다.
- gate 변화: 없음. 이름·문서·정적 화면 범위이며 설치·실물 실행·DEVICE/FIELD 수용을 바꾸지 않는다.

## 2026-10-19 · 9c1160981c · D-806 이름 정합 검증 완료

- 변경: 이전 Cell 안내·지도 제목을 기대하던 브라우저 검사를 승인한 이름으로 맞췄다. Games 480px·600px 검사를 추가했다.
- 증거: 구현 689cb1e968의 원격 affected 8,767 passed / 889 skipped, 관측 서비스 647 passed. Chromium 230 passed와 이전 문구 기대값 4 failed는 9c1160981c에서 수정 후 4 passed, Games 중간 폭은 989b806b34에서 2 passed. 최종 비교 NEW 0. 커밋·로그·실행 범위는 docs/validation/app-names-2026-10-19/result.md에 기록했다.
- gate 변화: 없음. main 병합·push·배포·실물 수용은 수행하지 않았다.

## 2026-10-19 · 103df862b · 관리자 임시 비밀번호 입력의 ID! 초기값 지원

- 변경: 관리자 생성·초기화의 임시 입력만 최소 길이2로 조정했다. 정확한 ID! 예외는 서버가 검증하고 다른 짧은 값은 거절한다. 본인 첫 변경·프로필의8자 조건은 유지한다.
- 증거: 실제 Chromium에서 짧은 초기값의 관리자 생성이 HTML 검증으로 막힘을 먼저 재현했다. 생성/reset→본인 제한 로그인→변경→프로필 복귀와 외부 변경 뒤 관리자 revision 재조회 검사를 추가했다.103df862b의 서버·실제 Chromium6파일160 passed·skip0·NEW0. 상세 범위는 docs/validation/account-initial-password-2026-10-19/result.md.
- gate 변화: 없음. 운영 사용자·프로필·설치 화면은 변경하지 않았으며 실제 사용자 로그인 수용은 미확인이다.

## 2026-10-19 · 39f94f151 · (origin #92 2026-10-16) 충전 운행 주체 오류 안내와 Console 회귀

- 변경: TRIP_OWNER_KIND_INVALID에 운영자 안내를 추가했다. 오류 표의 같은 줄 객체 항목도 검사하도록 정적 label 검사를 바로잡았다. 기존 800줄 상한과 화면 경로·배치를 유지한다.
- 증거: 5a33eabd4의 영향 범위 22개 파일을 ROSY_RUN_BROWSER_TESTS=1로 실행해 실제 Chromium 457개가 통과했고 skip은 0이다(task-7-charge-owner-label-browser/run-1.txt). 같은 명령에 추가한 비브라우저 label 검사 1개는 당시의 줄 시작만 보는 parser로 실패해 명령 종료 코드는 1이다. 이 parser를 8ddf4981f에서 수정했고 39f94f151의 최종 계약/회귀 486개에 해당 검사가 포함되어 통과했다(NEW 0/skip 0). UI source는 browser 실행 이후 바뀌지 않았다. 혼합 명령 전체를 GREEN으로 기록하지 않는다.
- gate 변화: 관련 UI 회귀 근거를 추가한다. 충전 운영 화면의 전체 상태·주기 정책·이안/재투입과 실기 수용은 미완료다.

## 2026-10-19 · 8c6692128 · (origin #92 2026-10-17) 설치 보정 손잡이의 상단 바 가림 수정

- 변경: 실측 교정 패널로 늘어난 화면에서 기존 사각 보정 손잡이를 스크롤하면 고정 상단 바에 가려졌다. 손잡이의 스크롤 시작 여백에 공용 앱 바 높이와 간격 토큰을 적용했다.
- 증거: 병합 전 전체 원격 검사 ea71743778의 `test_camera_rectification_direct_manipulation`이 실제 hit test에서 실패했다. 8c6692128의 같은 드래그 검사와 실측 교정 브라우저 두 폭은 3 passed, NEW 0이다. 원본 로그는 저장소 밖 `C:/DevTemp/camera-calibration/landing-handle-fix/`에 있다.
- gate 변화: 없음. 수정본과 최신 main의 전체 병합 검증은 별도 수행한다.

## 2026-10-20 · uncommitted · 관제 AI 패널과 로컬 음성 adapter

- 변경: 접히는 관제 AI 패널, 전송·결과 조회·근거 시각, 계정 변경 즉시 격리, 페이지 복귀 후 읽기 재개와 선택적 로컬 한국어 음성 입출력을 추가했다.
- 증거: dab629c171 실제 Chromium 회귀 25개 통과·skip 0. 새 대화와 기존 개입/배치 흐름을 데스크톱·모바일에서 검증했다. Node 상태·음성 시험 8개 통과. 마이크와 모델 응답은 fixture이며 실제 한국어 품질은 미확인이다.
- gate 변화: 없음. 운영 브라우저 음성 수용·모델 활성화·배포는 수행하지 않았다.

## 2026-10-20 · a1f0252d0a · D-821 한국어·영어 대화와 로컬 음성 선택

- 변경: 한국어/English 선택을 텍스트 요청과 로컬 인식·읽기에 연결하고 언어 변경 시 인식을 취소한다. 원음 업로드나 자동 전송은 없다.
- 증거: 실제 Chromium 26개·skip 0, 전체 Console Node 343개 통과. 선택한 locale 전송과 영어 답변 표시, 로컬 영어 인식/읽기를 검증했다.
- gate 변화: 없음. 실제 관제 PC 마이크·발화 품질·로컬 팩 지원은 별도 수용이다.

## 2026-10-21 · uncommitted · 계정·로그인·프로필·정책 문서의 테마 단추

- 변경: 테마를 따르지만 바꿀 길이 없던 네 문서(계정, 로그인, 내 계정, 학습 정책)의 앱 바에 공용 `[data-theme-cycle]` 단추를 넣었다. 배선은 ui.js 하나다.
- 증거: 정적 점검. 원격 브라우저 검사는 별도 기록한다.
- gate 변화: 없음.

## 2026-10-22 · aa784c548f · fix: Auth 승인 거부의 로그인 복구

- 변경: 공통 로그인 화면에서 승인 거부·잘못된 요청·연결 장애를 구분하고 계정 권한 확인·명시적 재시도·다른 계정 로그인을 제공한다. 복구 화면에서는 기존 쿠키만으로 거부된 요청을 자동 반복하지 않는다. 세션 검증과 첫 비밀번호 변경은 유지한다.
- 증거: f2d7ea9d21 원격 계정·로그인·Learning Chromium 7개 통과. 후속 반복 장애 수정과 main 병합 후 검증은 착지 기록에서 확인한다. 독립 검토의 반복 장애 재시도 버튼 지적을 수정했다.
- gate 변화: 실제 운영 배포와 사용자 계정 수용은 별도다.

## 2026-10-22 · 517c462d68 · fix: 로그인 복구 경로의 API 대응표 등록

- 변경: 로그인 화면에서 판별하는 authorize 복귀 경로를 기존 GET authorize 계약과 연결했다.
- 증거: 전체 회귀에서 대응표 누락을 재현했다. 기존 원격 HTTP 계약과 회귀 검사를 그대로 사용하며 착지에서 재검증한다.
- gate 변화: API와 권한 동작 변경 없음.

## 2026-10-22 · uncommitted · D-841 등록·페어링의 공통 HTTP 전송 소비

- 변경: enrollment·camera-pairing이 기존 request.js를 사용한다. 화면별 detail·자격·수명 처리는 유지하고 camera-peer는 제외한다.
- 증거: 새 소비자 회귀 9개 중 기존 코드의 2개 실패를 확인한 뒤 전체 Fleet Node 352개 통과, skip 0. 원격 브라우저 회귀는 후속 검증한다.
- gate 변화: 소스·Node 범위이며 장치·현장 수용은 아니다.

## 2026-10-22 · uncommitted · D-845 camera-peer 공통 요청 전환

- 변경: camera-peer가 main에 먼저 반영된 createRequest의 요청별 readResponse를 소비한다. 기존 헤더 시점 권한 처리·엄격 JSON·화면 수명 검사·단일 승인을 유지한다.
- 증거: 실제 파일과 기존 Node loader로 전환 전 8 passed/1 expected failure, 전환 후 새 9개와 기존 2개 모두 통과했다. 원격 소비자·브라우저 검증은 후속 기록으로 구분한다.
- gate 변화: 공통 전송 소비 범위다. 장치·현장 수용은 추가하지 않는다.

## 2026-10-23 · uncommitted · 계정 칸은 사용자가 열 때만 열린다

- 변경: 잠금·401에서 계정 칸(`#topbar-extra`)을 스스로 열던 길을 없앴다. `showSignedOut`의 `fold` 옵션, `connectionView.open()`, `openedForLock` 추적을 지우고, 관제는 안내 띠의 `관제 접속`으로만 연다.
- 증거: 노드 계약 시험 `fleet-header.test.mjs` 11 passed — 잠금 뒤 `data-open`이 `false`로 남는 단언을 넣었다. 브라우저 회귀는 착지 검증에서 다시 본다.
- gate 변화: 화면 동작 변경(로그인 전·잠금 화면이 닫힌 계정 칸으로 시작). API·권한 동작 변화 없음.

## 2026-10-23 · uncommitted · 세션은 들어온 계정 줄을 다시 접는다

- 변경: 접속이 서면 `showSession`이 계정 칸을 접는다. 자동 열림을 지운 뒤에는 줄을 열어 토큰을 넣은 사용자가 머리 두 줄을 계속 보게 되므로, 접속이 증명되면 말로 바뀐다(D-741 3).
- 증거: `fleet-header.test.mjs`에서 줄을 연 뒤 `showSession`을 지나 `data-open`이 `false`가 되는 단언으로 고정했다. 셀 브라우저 시험은 토큰 칸을 만지는 곳마다 기존 `open_token_access`를 거치게 했다(4곳).
- gate 변화: 화면 동작 변경(접속 뒤 한 줄 머리 복귀). API·권한 동작 변화 없음.

## 2026-10-23 · uncommitted · 공통 동작 모음과 로봇 선택 이동 적용

- 변경: 개입·재계획 동작 모음에 공통 줄바꿈을 적용하고 지도 머리에서 기존 로봇 선택 영역으로 초점을 이동한다. 기존 확인 라벨·API·명령 의미를 유지한다.
- 증거: 앞선 `1cc26ebd37`의 Fleet 회귀 33 passed와 최종 `37951c2501`의 동일 실행 소스를 별도 착지 단위로 옮겼다. 현재 main 통합은 공식 착지 도구의 고정 SHA 회귀로 검증한다.
- gate 변화: 없음. 호스트 화면 검증이며 실제 로봇·현장 수용을 뜻하지 않는다.

## 2026-10-24 · 290c8344a0 · 관제 간 요청과 현장 승인 작업면

- 변경: 기존 작업 화면에 관제 범위·목표·위임 출처·stale와 현장 승인/취소 요청을 연결했다. 미확인 body/ID는 사용자별로 보존하고 원장 재조회 없이 새 요청으로 바꾸지 않는다. 접수 전 확정 거절의 수정과 키보드 포커스 복원을 지원한다.
- 증거: 실제 Chromium36 PASS(기존 작업면 포함), 별도 1366/320·dark/light·미확인 재적재/거절 복구6 PASS. [검증 기록](../../../docs/validation/control-unit-pipeline-2026-10-24/result.md). 합성 fixture이며 실제 장치 상태가 아니다.
- gate 변화: 집중 소프트웨어 경로만 확인했다. 최종 통합 검사·착지·현장 화면 수용은 별도다. CE 해당 없음.

## 2026-10-24 · uncommitted · TRIP 요청 조회 불가 문구

- 변경: 새 중립 TRIP 조회의 TRIP_JOB_NOT_FOUND에 요청 번호·접속 계정을 확인하는 문구를 추가했다. 권한 밖 원장의 존재를 구별해 알리지 않는다.
- 증거: f3d7d3fba5의 기존 trip 오류 문구 coverage가 누락을 재현했다. 52a9ccf6b5에서 이 coverage를 포함한 관련 원격 261 passed, skip 0이다.
- gate 변화: 문구 표 한 줄이며 화면 구조·동작·실물 변경은 없다. CE 해당 없음.

## 2026-10-24 · uncommitted · 운행 오류 문구 표 분리와 크기 회귀

- 변경: 기존 788줄 site-map-model에 라벨을 추가하는 대신 표를 trip-error-labels.js로 옮기고 기존 export를 유지했다. 자산 manifest를 등록하고 source ratchet을 720줄로 낮췄다. 구버전 표의 다른 코드 맵을 포함하는 coverage와 공유 문서 import 경계를 함께 연결했다.
- 증거: 34ff5f55c1의 원격 라벨 coverage·문서 import·서버 자산·모듈 구조 회귀 94 passed, skip0, 0 NEW다. 기존 node 모델 소비자 6개 suite는 63 tests/exit0이며 f3d7d3fba5..34ff5f55c1 크기 검사 8 commits가 통과했다. 추출 소스의 독립 검토를 받았다.
- gate 변화: 공개 import·자산 제공을 보존했다. 전체 FULL은 이전 f3의 실패 기록이며 수정 범위의 GREEN과 구별한다. CE 해당 없음: 모듈·manifest·기존 coverage로 변경 판단을 복원할 수 있다.

## 2026-10-24 · e1e69f32c7 · 관제 UI 표시·수명·스타일 경계 분리

- 변경: 운행 표시를 trip-display, 목록 표현을 roster-presentation, 로스터 전용 스타일을 roster.css로 분리했다. 셸은 로스터 공개 과업 동작을 쓰고 기존 권한·요청·폴링·초점을 유지한다. 실제 소비자·자산 registry·문서 로드를 함께 갱신했다.
- 증거: 원격 집중44 passed/2 warnings/0 NEW, 4폭×2테마의 계산 스타일 일치. [검증 기록](../../../docs/validation/fleet-ui-boundaries-2026-10-24/result.md). 최종 완결 커밋의 공식 착지 검증은 별도다.
- gate 변화: 없음. 합성 호스트 UI 검증이며 장치·사용자 G3·현장 수용은 미실시다. CE: 부모 Python stdout의 UTF-8 복구 교훈을 docs/solutions에 기록했다.

## 2026-10-24 · afb218aed1 · 최신 운행 오류 문구의 표시 소유 보존

- 변경: main의 TRIP_JOB_NOT_FOUND 문구를 새 trip-display 소유로 통합했다. 지도 fitView 선언 정리를 유지하고 지도 ratchet을606으로 낮췄다. 문구 반환 Node 단언을 추가한다.
- 증거: [통합 기록](../../../docs/validation/fleet-ui-boundaries-2026-10-24/2026-10-24-main-label-integration.md). 고정 커밋의 오류 어휘·Node·소유·8화면 집중 검증과 공식 착지 결과는 후속 보고로 구분한다.
- gate 변화: 없음. 동료 실행 계약·권한·문구는 유지한다. CE 해당 없음: 기존 소유 설계와 회귀에 판단을 남겼다.

## 2026-10-24 · uncommitted · 설치 화면의 장치 정보 (D-860)

- 변경: 기존 설치 작업에 장치 정보 조회·신규·수정을 추가한다. 저장된 ID와 편집 이름을 나누고, 실제 연결은 미확인으로 표시한다. 기존 계정·요청 수명·UI 구성요소를 사용한다.
- 증거: 7652ea871c 원격 RED에서 누락 자산과 설치 연결을 확인했다. 최종 Node·브라우저 검증은 후속 결과로 기록한다.
- gate 변화: 장치 연결·보정·모터 제어를 이 화면의 저장으로 허용하지 않는다.

## 2026-10-24 · 9a0f3ae2b2 · 장치 정보 화면 원격 수용

- 증거: [검증 기록](../../../docs/validation/device-information-2026-10-24/result.md). 실제 설치 HTML·자산으로 Operator/Viewer와 1440px/390px의 Chromium 4개를 활성 실행했고 캡처를 육안 확인했다. 기존 Console Node 전수·운영자 문구·레이아웃 관문도 통과했다.
- 범위: 브라우저의 HTTP 응답은 스텁이다. 실제 DB/API 검증은 별도 통합 시험이며 운영 UI 배포와 장치 수용은 수행하지 않았다.
- 변경: 실제 설치 화면의 편집·재조회·읽기 권한과 캡처 확인 결과를 검증 기록에 연결했다.
- gate 변화: 화면의 소프트웨어 증거만 추가했다. 운영 배포·실물 동작 수용은 미실시다.

## 2026-10-25 · uncommitted · D-862 관제별 정보·지도·정지 요청 화면

- 변경: 기존 delegation 화면에 통합 tree/detail/evidence/task와 소유 단위별 읽기 전용 지도를 연결했다. 하위 정지와 단위별 UNVERIFIED 결과·조회 이력·명시 로컬 재시운전 확인을 표시하며 auth/lifecycle reset을 유지한다.
- 증거: 준비 patch의 JS/JSON/Python 구문과 독립 범위 검토를 확인했다. 실제 browser·Node와 backend HTTP의 새 source 증거는 원격 GREEN 후 기록한다. feature matrix의 verified 등록도 실제 HTTP 통과 후 수행한다.
- gate 변화: 새 기능의 SOURCE/원격 검증을 진행하며 배포·장치·FIELD 승격은 없다. CE 해당 없음 — 현재 판단은 ADR·소스·회귀에 남기고 검증 전 해결 교훈을 쓰지 않는다.

## 2026-10-25 · uncommitted · viewer의 관제·지도·정지 이력 조회 유지

- 변경: 통합 화면의 읽기 버튼에 기존 data-work-read 표기를 적용했다. 공통 operatorControls가 동적 버튼을 운영 조작으로 잠그던 원인을 수정하며 정지 쓰기·재시운전 버튼의 운영자 제한은 유지한다.
- 증거: source10fc372212 실제 Chromium에서 UNKNOWN/PARTIAL viewer2건이 이력 버튼의 운영자 잠금으로 실패했다. 해당 시험에 viewer의 관제 선택·지도·같은 정지 기록 조회와 쓰기 금지를 함께 추가해 수정 source를 원격 검증한다.
- gate 변화: 읽기 권한과 운영 조작을 구분하는 UI 수정이며 backend 권한·실제 장치 수용은 바꾸지 않는다. CE 해당 없음 — 원인을 코드의 공통 잠금 표기와 실제 browser 회귀에 직접 남긴다.

## 2026-10-25 · uncommitted · 정지 응답이 overview보다 먼저 갱신되는 경우의 로컬 세대 선택

- 변경: 신선한 overview를 전제로 같은 authority epoch의 더 최신 로컬 정지 응답 세대를 재시운전 확인에 사용한다. 이전 응답으로 세대를 내리거나 다른 epoch·오래된 overview를 통과시키지 않으며 원래 정지 body와 자동 전송 정책은 유지한다.
- 증거: source0b30c65d59의 실제 standalone sample browser가 정지 직후 이전 overview 세대를 보내 복구 결과를 갱신하지 못했다. 직접 API 회귀39건과 CORE 연계21건은 별도 source에서 통과했으며, UI에 최신 응답/이전 응답/다른 epoch/stale overview4회귀를 추가했다. 수정 source의 실제 sample/browser 통과는 후속 실행이다.
- gate 변화: 재시운전 확인은 현재 backend generation 검사와 사람의 두 확인·근거를 계속 요구한다. 물리 정지나 자동 재무장 증거가 아니다. CE 해당 없음 — 원인을 코드 주석과 실제 sample/browser 회귀에 남긴다.

## 2026-10-25 · uncommitted · 통합 재시운전 확인 입력의 공유 UI 적용

- 변경: checkbox label에 기존 ui-check를 적용하고 textarea의 ui-field 설정을 생성 위치로 옮겼다. 입력 의미·기명 권한·원장 처분은 유지한다.
- 증거: source42e079ef48 FULL의 공유 입력 검사1 FAIL을 source79ff20cc96에서 수정했고 해당 원격 회귀1 PASS·SKIP0·NEW0이다. 기존 sourcebbffbf8577의 집중 Chromium/Node33건과 source42e079ef48의 명시 Chromium4그룹은 각각 통과했다. 최종 수정 source의 공식 FULL은 후속 실행이다.
- gate 변화: 공통 입력 표현을 맞추며 장치·현장 수용을 승격하지 않는다. CE 해당 없음 — 원인과 수정 조건이 기존 공유 UI 검사에 직접 남는다.

## 2026-10-26 · 62173b9899 · 앱 바 높이 덧쓰기 정리

- 변경: 공용 `ui-topbar`가 D-741 앱 바 높이(64px)를 기본으로 갖게 되어 이 표면의 같은 값 덧쓰기를 지웠다(Pilot은 두 줄 머리 높이를 명시로 유지).
- 증거: 원격 서버 시험 8f85ca2d0f 기준 shared/web·Robot·Fleet·Pilot 471 passed/0 NEW, Learning 브라우저 2456 passed/1 NEW(왼쪽 정렬 누락, 고친 뒤 89421d5732 해당 5묶음 210 passed/0 NEW). 이 커밋은 착지 시험(land.py --tests auto)이 다시 돈다.
- gate 변화: 없음.

## 2026-10-27 · uncommitted · 모바일 관제와 작업 화면 위계 개선

- 변경: 모바일 로봇 선택·상태·작업을 지도보다 먼저 배치하고 DOM 이동 순서도 D-892에 맞췄다. 로그인 도움말·계정 구획·작업 연동 접힘·Cell 단계 열기를 정리했다. 인증·승인·명령 경로와 넓은 화면 배치는 유지한다.
- 증거: 소스 d15e7a9545의 명시 원격 묶음은 537 PASS·2 FAIL이었다. 실패 두 건은 옛 모바일 순서를 검사했으며 보이는 순서와 DOM 순서를 함께 수정해 재검증한다. 앞선 선택 전·후 배치·소유권 6건과 Node 60개 파일은 통과했다. 전체 affected/FULL 통과를 뜻하지 않는다.
- gate 변화: 제품·장치·현장 수용 승격 없음. 샘플 계정 전환 후 간헐 조회 실패는 원인 미확정이며 시험 실패 진단을 보존한다.

## 2026-10-27 · uncommitted · feat: 로봇 정보 확인 후 조치하는 상세 프로필

- 변경: 로봇 상세와 Cell 팔에서 실시간 관측 다음에 주의사항·특성·최근 분석·기록을 표시한다. 기존 조작은 그 아래에 유지한다. 설치 화면은 명시 연결·기록·특성 파일 편집을 맡고 미저장 초안을 보존한다. 서버뿐 아니라 브라우저에서도 capture 근거의 나이를 반영한다. 공용 정지는 프로필 조회와 독립이다.
- 후속: 최근 진단을 특성보다 먼저 배치하고 기존 출처 펼침에서 owner·원본 시각·전체 특성 해시를 확인한다. 현재 Cell 등록 owner·지문과 늦게 도착한 응답을 대조해 다른 팔의 기록을 숨긴다. 관련 실제 브라우저 회귀와 Node 395건 PASS; FULL 병합 검증은 별도다.
- 증거: UI commit `bf3470f9fe`의 원격 Chromium PC·모바일·Viewer/Operator 10건 PASS·NEW 0. 캡처에서 모바일 버튼 압축을 확인해 기존 flex basis를 바꾼 뒤 commit `8ce8e21139`의 관련 Chromium 6건 PASS. `docs/validation/robot-profile-pipeline-2026-10-27/result.md`에 기록한다.
- gate 변화: 실물 장치·운영 배포는 수용하지 않는다. 오래된 분석과 조회 불가는 현재 정상의 근거가 아니다.

## 2026-10-27 · uncommitted · D-865 P3 승인 범위 readback과 자동 승인 배지

- 변경: work 뷰가 `GET /api/fleet/policy-admission`을 함께 읽어 승인 대기 행에 범위 소속 배지(`자동 승인`)를 붙이고, work 개요에 범위 readback(로봇·종류·잔여 상한·revision·차단 사유)과 기명 운영자 전환 단추를 둔 `<details>` 패널을 추가했다. 판정·문구는 순수 함수(`autoAdmitScope`·`policyScopeText`·`autoAdmitDetail`)이고 readback이 없으면 fail-closed로 배지를 끈다. 범위 밖 로봇·`two_person`·상한 소진·전환 꺼짐은 배지 없이 사람 승인으로 남는다. 새 자산이 없어 allowlist·CSP는 그대로다.
- 증거: node `work-view.test.mjs` 6 통과(범위 안·로봇 밖·two_person·소진·비활성·readback 문구). 모델 PC 원격 `ROSY_RUN_BROWSER_TESTS=1`로 `test_work_overview_browser.py` 36 통과·`test_console_palette`·`test_console_disabled_features`·`test_document_imports`·`test_doc_tabs` 포함 0 NEW, `test_server_app`·`test_remaining_platform_installed` 50 통과 0 NEW. 전체 affected/FULL 통과를 뜻하지 않는다.
- gate 변화: 제품·장치·현장 수용 승격 없음. 자동 승인 활성화는 P5 현장 수용 기록이 별도다.
