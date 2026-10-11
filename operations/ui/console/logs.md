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
