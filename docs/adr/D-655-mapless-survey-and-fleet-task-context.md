## D-655 지도 없는 조사 좌표·도로 시설과 통합 관제 작업 맥락

**Status:** Accepted (2026-10-11, 사용자 구현 요청; 구현·배포·실물 수용 별도)

### Context

사용자는 완성된 지도 파일 없이 기준점·도로 요소를 등록하고 카메라 관측과 로봇 주행으로 지도를 쌓도록 요청했다. 로봇 선택 → 작업 배정 → 진행·문제 확인을 주 흐름으로 정했고, 개입과 대형 운용도 포함했다. D-497 차선 초안과 D-494 6 주행 가르치기, D-635 프로필, D-651 선택 작업 영역을 확장한다.

### Decision

1. `rosy.site_map/1`에 선택 `survey`, `facilities`, edge의 선택 `evidence`를 추가한다. 없는 기존 지도는 직렬화와 해시를 바꾸지 않는다. `survey`는 조사 기준 `revision`, `origin [x,y]`, `heading_rad`, `scale_source: odometry|measured`, `measured_distance_m?`, `description`, `reviewed`, `review_note`다. 좌표 단위는 기존 m이며 원점과 방향은 조사자가 지정한다. measured는 실측 거리 필수다. odometry는 장치의 기존 m 단위를 사용하지만 외부 실측 정확도나 사이트 위치 확정을 뜻하지 않는다. reviewed가 참이면 review_note가 필요하다. 메타데이터로 CORE/World의 운행 MapPose를 변경하지 않는다.
2. 도로 근거는 `source: camera|odometry|operator`, `status: observed|inferred|reviewed`, `reference_revision`, `note`다. 검토된 근거에는 note가 필요하고 조사 기준이 있으면 revision이 같아야 한다. 조사 기준 미검토 또는 도로 근거 observed/inferred인 지도는 활성화가 거절된다. 화면은 근거를 구분하며 미관측 연결을 관측 도로로 바꾸지 않는다. AI는 추정 연결과 검토 도움만 제공한다.
3. 시설은 `{id,name,kind,geometry,approaches,signal_id?,signal_kind?}`다. kind는 traffic_signal/stop_line/landmark/exclusion, geometry는 같은 조사/지도 좌표의 점·선·영역이다. 신호등/landmark는 한 점, 정지선은 두 점, 금지 영역은 3–32개 점이다. approach는 `{edge_id,forward,stop_s_m?}`이고 존재하는 차로만 참조하며 stop_s_m은 해당 차로 길이 안이다. signal_kind는 physical/virtual이며 신호등만 signal_id와 함께 가진다. 시설 그림은 장치 등록이나 신호 운행 활성화가 아니다. 물리 장치의 인증·관측과 가상 신호의 구역/진입 설정은 기존 D-525 경로와 구분해 연결한다. 중복 ID·비유한 좌표·잘못된 기하·끊긴 차로 참조를 거절한다. 금지 구역에 닿거나 차로 반폭 이내인 간선이 남아 있으면 활성화를 거절한다(`SITE_MAP_EXCLUSION_OVERLAP`).
4. 지도 없는 시작은 예제 차로 없이 빈 초안을 만든다. 조사 시작점·방향과 축척 근거를 입력하고 시설·도로를 추가한다. camera lane 추출은 기존 보정·폭·시드 기반 도구를 재사용하고 근거와 함께 초안에 합친다. 기존 `map_v2_fleet / 260919 MAP FILE.STL` 계보와 활성 버전을 자동 교체하지 않는다.
5. teach는 기존 확인된 map pose 기록을 유지한다. 별도 명시적 조사 모드는 신선한 odom을 시작 조사 기준으로 변환해 초안용 기록만 만든다. 이 변환을 map pin으로 구현하지 않는다. odom 시각 역행·재시작·위치 점프·관측 공백·조사 revision 교체는 기록을 끊거나 멈추고 이유를 남긴다. 손실 구간을 RDP 선으로 연결하지 않는다. 조사·카메라 결과 추가는 기존 draft revision 검사로 보호한다.
6. 선택 로봇 작업 영역에서 목적지/차선 작업/지도 기록과 대형 상태·구성을 연결한다. 로봇/그룹 선택만으로 명령을 보내지 않는다. 대형 리더만 목적지 명령을 받고 팔로워는 기존 대형 계약을 따른다. 충돌하는 단독 작업은 기존 취소/대형 해제 순서를 따른다. attention·개입 큐·전체 정지는 작업 탭 밖에서 접근 가능하다. 접수와 실제 실행·종료를 구분하고 알 수 없는 수신자는 unknown으로 유지한다.
7. API reference와 `core_common.protocol.schemas`의 조사·시설 모델 re-export를 같은 변경으로 기록한다. 외부 endpoint를 추가하기 전에는 계약에 요청·응답·권한·오류·시각을 먼저 기록한다. 이전 API envelope version은 그대로다.
8. 활성 지도 교체는 기존 trip뿐 아니라 대형의 ARMING/RUNNING/HOLDING 및 진행 중 teach 기록에서도 기존 409 `SITE_MAP_ROUTE_ACTIVE`로 거절한다. 초안·프로필 저장과 멈춘 기록의 검토는 가능하다. busy 검사와 활성 버전 쓰기는 같은 이벤트 루프에서 await 없이 실행해 그 사이 운용 시작이 끼지 않게 한다. 거절은 지도·기록·대형을 바꾸거나 로봇에 명령을 보내지 않는다. 운용 종료 뒤에도 원래 draft revision 검사와 별도 활성화 조작이 필요하다.
   일반 기록 시작과 현재 로봇 위치의 장소 저장은 위치 조회 전 map_id·전체 조사 기준·활성 버전을 고정하고 조회 후 비교한다. 조회 대기 중 활성화되면 같은 map_id여도 `TEACH_MAP_CHANGED`로 거절하며 이전 위치를 새 지도에 쓰지 않는다. 개별 목표/운행의 화면 사유는 기존 trip·대형 admission을 따르고 충돌하는 작업을 자동 해제하지 않는다. 복구 명령 수락은 실제 주행 확인과 구분한다.

| 기존 결정 | 관계 |
|---|---|
| D-427 | operations/fleet, operations/world, operations/vision, operations/ui/console의 기존 소스 소유와 배포 묶음 재사용; 새 최상위 폴더 없음 |
| D-429 | 관측·배정·장치 실행 역할 유지; 그림에 시설을 추가하는 것이 장치 실행 포트가 아님 |
| D-430 | 조사 좌표는 운행 pose 입력이 아님; CORE 최종 명령 소유·안전 가드 유지, safety 경로 변경은 독립 리뷰 필요 |

### Verification

빈 지도·기준 검증·시설의 차로 참조·구버전 body 보존·DB 재개방·revision 충돌·viewer 잠금, 관측 공백과 odom 재시작, 조사 결과 활성화 거절과 명시적 검토를 원격 검증한다. 선택 변경의 무명령, 대형 충돌/해제 순서, 문제 개입의 부분 실패·readback, desktop/mobile 지도 크기·가독성을 검증한다. 정확한 CI SHA·서명 릴리스·설치 image와 실제 사이트 동작을 기록한다.

### Consequences

지도 생성과 관제 작업을 같은 흐름으로 사용할 수 있는 근거·관계 계약이 생긴다. 도로 추정과 조사 기록은 검토 대상으로 남고 운행에 자동 쓰이지 않는다. 코드·합성 시험·배포는 실물 주행·측량 정확도·대형 수용을 대신하지 않는다. 구현 상태와 순서는 [실행 계획](../plans/2026-10-11-mapless-fleet-control.md)에 기록한다.
