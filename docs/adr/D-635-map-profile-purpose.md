## D-635 지도 프로필의 용도와 기본 정보 및 Games 경기장 재사용

**Status:** Accepted (2026-10-11, 사용자 요청; 배포·현장 검증 별도)

### Context

사용자는 각 프로필에 지도 종류와 기본 정보를 저장·관리하도록 요청했다. D-631은 차로 지도만 저장한다. Games의 Field·SoccerGame·Observation은 경기장 치수·골대·공·공격 방향·득점·관측 유실을 이미 다룬다.

### Decision

기존 프로필 요청·응답에 `kind` (`lane_course`, `soccer`, `general`), `description` (최대 1000자), `soccer_field`를 추가한다. 경기장 정보는 `length_m`, `width_m`, `goal_width_m`이며 양의 유한 값, 골대 폭은 경기장 폭 이하다. soccer는 경기장 정보가 필수이고 다른 종류는 null이어야 한다. 기존 요청·저장 행은 lane_course, 빈 설명, null로 호환한다. SQLite 기본 정보 JSON 열을 추가해 데이터와 권한·revision 충돌·2 MiB·100개·감사를 보존한다. 기본 정보 변경도 새 revision을 만든다.

Console에서 종류·설명·경기장 치수를 입력하고 저장·다시 선택한다. 새 축구장 지도는 입력 치수로 중심 원점의 네 경계 점을 만들며 차로는 생성하지 않는다. 파일은 기존 지도 JSON 또는 저장된 프로필 행(map과 기본 정보)을 읽는다. 저장·선택은 지도 활성화·게임 시작과 별도다. 축구장 기본 정보를 차로 주행 초안으로 자동 변환하지 않는다.

공통 좌표·카메라 교정은 D-633/D-634를 따른다. 축구장의 선은 경계·중앙선·골대 의미이며 주행 차선으로 추론하지 않는다. 유형 템플릿은 인식 후보와 검증 기준이고, 보이지 않는 공·로봇·선을 실제 관측으로 만들지 않는다.

Games의 Field 기하·SoccerGame 심판·정책을 재사용한다. 이번 구현은 기본 정보 관리·경계 템플릿까지다. Games 자동 실행 설정이나 Vision 축구 인식 활성화는 별도 구현이다. 그 연결은 map/source/calibration/profile revision, metre 지도에서 Games 중심 좌표로의 위치·회전 변환, 공/로봇 식별·관측 수명·유실 HOLD를 검증한다. games.field/game/policy에 Fleet·HTTP·cv2를 넣지 않는다.

### Verification

API 기본값·치수 거부·revision 충돌, 기존 DB migration과 재개방, 브라우저 입력·저장·선택·파일·경계 생성·활성 지도 보존을 검증한다. 실제 경기장 치수·교정·게임 수용은 별도다.

### Consequences

용도별 기본 정보를 관리하고 향후 Games와 인식에 연결할 기준을 제공한다. 지도 이름만으로 종류나 교정 성공을 추론하지 않는다.
