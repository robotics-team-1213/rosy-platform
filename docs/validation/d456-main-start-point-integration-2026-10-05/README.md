# D-456과 main의 시작점 기능 통합

독립 검토자 `/root/ship_fleet_cam_merge`: SPEC·Quality·Safety SOURCE PASS.
검토 영수증 SHA256: `6db7f290d3f6025b37a08f102b70fc60a2e9606d6c82fedca8f8f8e09b972174`.

새 시작점 소유자는 승인된 calibration/map/revision과 finite 좌표, expected revision을
확인해 SQLite 참고 기록을 저장한다. 기존 operator 정책을 유지하며 CORE 호출·로봇
위치 초기화·주행·grant 발급으로 전달하지 않는다. 선택 중 일반 goal 클릭을 막고
page scope 종료에 선택과 표시를 정리한다. 추적 활성일 때만 설치하며 lifespan 종료에
저장소를 닫는다. 기존 camera-peer와 lane route의 권한 검사·설치는 유지된다.

D-362 재판단: Fleet 35,137줄. 이전 통합 34,823줄보다 314줄 증가했다(참고 기록 backend
134, UI 172, composition/static 8). 그 이전 34,792줄과의 차이 31줄은 route 추출이다.
새 backend 모듈은 91·43줄, UI 모듈은 120·35줄로 책임을 나눈다. Fleet의 B2/UI 분리
대기열과 package +150, production 600/web 800, 1000 초과 파일 성장 0 규칙은 유지한다.

app.py는 602줄로 600 검토 기준을 넘었다. 기존 하나의 구성·lifespan 소유자로 accept를
기록하며 실제 승인·참고 저장 로직은 별도 모듈에 둔다. 파일 기준 600을 올리지 않고
일반 재성장 +150만 유지한다. console은 1,159줄로 변하지 않는다.

양쪽 additive minor가 v1.103을 사용해 통합 API Reference를 v1.104로 기록했다.
두 규약을 보존하고 해당 header pin만 동기화한다. envelope 1.0은 유지한다.

초기 통합 SOURCE 검사 102 PASS와 opt-in Chromium 3 SKIP를 구분한다. 해당 실제
브라우저를 명시 실행해 3 PASS(26.52초)를 확인했다. 크기·비밀 검사 3 PASS이며
harness lint는 오류 0·기존 경고 21이다. signed CI·site·Android 설치·물리 LAN 승인은
이 소스 검토에서 완료로 표시하지 않는다.
