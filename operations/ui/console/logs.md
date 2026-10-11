# console_source verification log

## 2026-10-11 · 962fa15277 · D-655 reviewed camera connections and pending writes

- 변경: 지도 밖 연결 후보·거리·선택·실제 연결 확인을 focused site-map-camera.js가 소유한다. 선택한 장소 ID를 유지하며 파일·초안·미저장 편집·선택·접속 변경이 대기 중 저장을 취소한다. 활성 지도와 이동 권한을 바꾸지 않는다.
- 증거: Node 29 PASS, 자원 기준 통과 AI PC Chromium 16 PASS/63 deselected, NEW 0. desktop/mobile 파일 읽기와 교체 확인 창 경합에서 이전 요청이 저장되지 않는다. terminal 로그는 `X:/DevTemp/projects/rosy-platform/2026-10-11--194243--mapless-fleet-control--384416/logs/camera-connect-race-green/run-1.txt`. 독립 검토 두 Important 수정 후 수용.
- gate 변화: source/remote 범위. 선택 로봇 작업·대형 연결, 개입, 통합·배포·실제 사이트 수용은 계속 진행한다. 실물 측량 정확도는 미확인이다.

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
