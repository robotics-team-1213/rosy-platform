# dashboard logs

추가만 한다. 형식: [module harness 설계](../../../docs/plans/2026-09-15-module-harness-design.md) §4.2.

## 2026-09-25 · uncommitted · refactor(hmi): operator screens leave the API package (D-243)

- 변경: `core_api_web/web`의 정적 파일을 이 패키지로 옮겼다. API는 설치 share 또는 이 소스 폴더를 읽는다
- 증거: 이 기록 직후 dashboard·gateway 대시보드 시험
- gate 변화: 신규. SOURCE GO, LOCAL GO, ARTIFACT HOLD, ROS-SIM/DEVICE/FIELD N/A
- 결정: D-243
- 교훈: 없음

## 2026-09-25 · 96654ed1 · feat(hmi): device card and motion reason (D-247)

- 변경: 점검 뷰 4번 카드 "장치" — 장치별 이름·버스·상태 칩(공용 [data-status] 어휘)·근거·`벤치 전용`·측정 시각, 관리자 "다시 점검". 운용 뷰 teleop 문구는 runtime mode로 막혔을 때 `motion_reason`을 보인다.
- 증거: `ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_dashboard_browser.py` 51 passed(Chromium)
- 미증명: 실기 대시보드
- gate 변화: 없음
- 결정: D-247
- 교훈: CORE-only viewer 상태는 1366×768에서 이전 문구로도 조작 열이 8 px 넘친다(feed2fc7부터). 문서 스크롤은 없다.

## 2026-09-26 · 88fbbe7f · feat(hmi): buzzer and lamp test buttons on the device card (D-247 6)

- 변경: 장치 카드의 부저·램프 행에 관리자 전용 "울려 보기"/"켜 보기"를 두었다. 드라이버가 없으면 꺼 둔다. 시험 결과 한 줄과 "들림·안 들림"/"보임·안 보임"도 보인다. 텍스트는 textContent만, 버튼은 공용 ui-button, CSS는 토큰만 쓴다.
- 증거: `ROSY_RUN_BROWSER_TESTS=1 python -m pytest test/test_dashboard_browser.py` 55 passed(Chromium)
- 미증명: 실기 대시보드에서 버튼을 누른 뒤 소리·빛
- gate 변화: 없음
- 결정: D-247
- 교훈: 없음

## 2026-09-26 · uncommitted · feat(hmi): add administrator hardware observation panel

- 변경: `/device`에 root probe의 장치별 상태·근거·측정 시각을 읽는 패널을 추가했다. 재점검은 기존 관리자 API만 호출하고, 이전 응답을 유지할 때는 stale로 표시한다.
- 증거: 화면 자산/매니페스트 계약 및 Chromium 패널 동작 시험. API 오류·쿨다운 상태는 서버 응답 문구를 표시한다.
- gate 변화: 없음. 테스트용 API 응답 브라우저 확인이며 Pi·실기 probe 결과는 확인하지 않았다.
- 결정: D-247의 관측/명령 경계를 그대로 쓴다. 이 패널은 hardware test나 사람 확인을 실행하지 않는다.
- 교훈: 마지막으로 받은 값은 접근 실패와 함께 stale로 표시해야 현재 관측으로 오해하지 않는다.

## 2026-09-26 · uncommitted · feat(hmi): extend role-based device and setup panels

- 변경: `/device`에 시스템 런타임·신원·CAP/inventory, Host Agent 네트워크·릴리스·커미셔닝 readback, 관리자 토큰 및 안전 한계 설정을 추가했다. `/setup`에는 Operator API 권한과 capability에 맞춰 초기 위치 입력 및 확인 대화상자를 둔 SLAM 시작·중지·저장 패널을 추가했다. 좁은 화면에서 상태 필드와 폼을 세로로 재배치한다.
- 근거: 패널/API 권한 계약과 manifest 시험, 대시보드/API 회귀, JavaScript 구문 검사, 선택 Chromium 회귀. `ROSY_RUN_BROWSER_TESTS=1` 대시보드/하드웨어 시험 57 passed.
- gate 변화: 없음. `/dashboard`의 기존 기능은 유지하며 이관 완료로 간주하지 않는다. 새 운전 콘솔, 도킹 준비 조작, ROS 그래프, 실제 네트워크/릴리스 조작, Pi/실기 검증은 남아 있다.
- 결정: 패널은 `panels.yaml`에서 추가하고 기존 API 계약의 최소 역할을 따른다. SLAM 조작은 Operator, 토큰/안전 정책은 Administrator다.
- 교훈: 새 페이지 readback은 Host Agent 릴레이 봉투(`available/data`)와 CORE 커미셔닝 직접 payload의 응답 모양 차이를 보존해야 한다.
