## D-676 Fleet 신호·CORE 교통 gate·차선 RL의 두 Pinky 완주 파이프라인

**Status:** Accepted (2026-10-12, 사용자 설계·구현 요청; 구현·native 실행·운영 수용은 미완료)

### Context

사용자는 기존 카메라 segmentation·line_follow·Drive 코드로 학습하고, 실제 맵의 네 신호 표시·횡단보도·사선 주의 표시·장애물·Fleet 순서를 지켜 두 Pinky가 완주하도록 요청했다. 기존 카메라 R12는 첫 training에서 유효 관측 0/22·updates 0이었다. 이전 네 방향 odom/path 완주를 카메라 정책 완주로 재분류하지 않는다.

D-638은 격리 한 대 CPU 진단, D-653은 장치별 owner·관측 신원 분리 준비다. 둘만으로 실제 Fleet와 두 articulation 연결은 구현되지 않았다. D-606의 Isaac Lab 자원·물리·ROS-SIM·실물 수용은 유지한다. 현재 기본 action은 조향 gain 네 값이며 속도·교통 규칙 학습이 아니다.

맵은 map_v2_fleet / 260919 MAP FILE.STL의 기존 곡률·흰 0.30m 사각 벽 파생이다. 사선 표식 공유 자산 source 28f6f4969를 기준으로 두 renderer의 맵·표식 계보를 맞춘다. 사선 class4 speed_bump의 ignore 역할은 교통 규칙을 무시하라는 뜻이 아니며 RGB 페인트와 분리한다. D-525 rev 5의 NE·SW는 진입, NW·SE는 진출이다. 네 표시가 네 동시 진입을 뜻하지 않는다.

### Decision

**실행 분담 변경(2026-10-12 사용자 지시):** 모델 PC의 headless Isaac은 한 대의 실제 카메라 segmentation 기반 학습·완주, 다른 AI PC의 headless Gazebo는 두 대의 CORE·실제 Fleet·교통·장애물과 각 로봇 완주를 검증한다. 아래 두 대 native Isaac 조건은 이 분담으로 대체한다. 두 renderer는 같은 지도 규칙·표식·벽·경로 계보를 사용하고, CORE 최종 권한과 실제 센서·정지 readback을 유지한다. 병렬 RL은 한 대씩 가진 독립 학습 환경 최소2개로 확인하며 두 대 Gazebo 실행만으로 학습 완료를 주장하지 않는다. Isaac 학습 결과와 Gazebo Fleet 검증은 별도로 기록하고 실물 수용은 계속 별도다.

**최종 주행의 입력은 실제 카메라 segmentation이다.** 이미 학습한 모델의 revision/hash를 고정해 native RGB에서 차선·주행 가능 영역·횡단보도·주의 표시의 기존 클래스 증거를 사용한다. 모델 재학습과 조향 정책 강화학습을 구분한다. 경로 지시는 분기 선택에만 사용하며 실제 카메라 target을 대신하는 정답 경로 조향으로 완주를 인정하지 않는다. 신호 인식은 기존 신호 관측 경로와 Fleet 상태를 함께 검증하며 segmentation에 없는 신호 클래스를 있다고 가정하지 않는다.

기존 모델의 `speed_bump` 클래스는 role `ignore`를 유지하되 같은 추론의 별도 마스크로 전달한다. paint worker는 횡단보도와 주의 표식 마스크를 각각 재사용·이동 보정·reset하며 배열을 JSON 진단 metadata와 분리한다. 클래스 없음은 관측 불가다. native trace의 픽셀 수는 표식 관측 진단이며 정지선 위치·점유 없음·통행 권한의 증거가 아니다. 이를 실제 주의 표시 앞 정지 gate와 연결하는 단계는 별도 검증한다.

**R12 회복 연결의 선행 조건.** 유효 target 상실 시 기존 zero 명령과 학습 업데이트 거부를 유지한다. 실제 native scan·pose를 기존 CORE 관측 접점에 연결하고 기존 회복 gate를 만족한 뒤 재관측한다. LiDAR mount를 두 번 적용하지 않고 physics 원본 시간·monotonic 수신 시간·Fleet pose authority 시간을 각 계약대로 유지한다. 무응답 scan은 UNKNOWN이며 최대 거리의 가상 hit로 바꾸지 않는다. 회전 여유는 prepared simulation collision 형상으로 검사하고, 회복 중 map-only 조향을 유효 camera 학습 state로 바꾸지 않는다.

**목표 판정은 셋으로 분리한다.** 기존 frozen 모델·CORE/Fleet 안전 규칙을 지키는 두 Pinky 전체 완주, 교통·장애물 실패 주입의 안전 정지/회복, fixed baseline 대비 RL 차선 오차·조향 흔들림 개선을 각각 입증한다. 단순 완주로 RL 추가 효과를 주장하지 않고 짧은 10초 실행을 full lap으로 세지 않는다. 유효 transition·updates>0과 독립 frozen-policy 짝 비교가 없으면 RL 성과는 미확인이다. 서버 신호 규칙을 학습하는 과제가 아니다.

**사용자 추가 요구: 실제 병렬 학습.** 동시에 실행되는 독립 simulation 환경을 최소 2개 둔다. 가능한 실행 설계는 한 Isaac SDK의 batched physics와 동일 frozen 모델 재사용으로 메모리 비용을 줄이는 것이다. 각 env_id는 독립 seed·episode epoch·local odom·두 로봇 CORE 상태·Fleet grant/lease/occupancy를 갖는다. 환경 간 후보·reset·관측·통행권이 섞이지 않아야 한다. env_id와 실제 timestamp의 겹침, 환경별 유효 transition·updates>0, 고정 정책·독립 heldout 짝 비교로 병렬 학습을 입증한다. 한 프로세스의 순차 episode, 병렬 pytest 또는 agent 작업을 병렬 simulation 학습으로 세지 않는다. 이 설계는 아직 구현되지 않았고 현재 camera R12는 한 환경·updates 0이며 병렬 실행 증거가 없다. 자원 배치 실패를 학습 통과로 바꾸지 않는다.

1. **파이프라인과 소유권.** 실제 native 센서→기존 frozen 모델/관측→기존 line_follow/Drive 조향 후보→각 CORE의 교통·장애물·권한 검사→각 native 몸체 순서다. Fleet의 기존 TripRunner·TrafficService·AuthoritySender가 경로·순서·grant/lease·공유 점유를 관리한다. 각 장치의 CORE만 최종 명령을 결정한다. 별도 예약 서버·최종 명령 publisher·운영 POLICY 우회 경로를 만들지 않는다.
2. **네 신호 표시와 첫 구역 용량.** 네 연결부에 방향·signal ID·지도 구역이 결속된 표시를 두며 구역 용량은 1이다. Fleet가 진입 순서를 정하고 표시 상태·카메라 관측·전달 권한의 revision/신선함을 함께 검증한다. NE/SW의 새 진입은 자기 방향의 유효 신호·신선한 grant/lease·상충 점유 없음·진출 여유·로봇 안전 관측을 모두 만족해야 한다. 다른 방향 초록이나 표시만으로 진행하지 않는다. NW/SE의 진출을 새 진입용 적색 gate로 막지 않는다. 통신/신호/권한이 낡으면 새 진입을 거절하고 이미 진입한 로봇은 기존 CORE 안전 조건 안에서 구역을 비우며 실제 관측으로 점유를 해제한다. 실제 장애물이 있으면 진출 보장 명목으로 강제 전진하지 않는다.
3. **횡단보도와 주의 표시 분리.** 이 맵 진단에서 D-573의 일괄 선행 정지 설계를 부분 구체화한다. 별도 정지 표시가 없는 일반 횡단보도는 서행하며 신선한 시야·횡단/진입 보행자 없음·장애물 없음·몸체 통과 공간을 확인하고 통과한다. 모름·가림·사람/진로 장애물은 진입 전 정지이며 시간 경과만으로 출발하지 않는다. 주황/검정 사선 주의 표시에서는 몸체가 경계를 넘기 전 완전 정지→주변/진로 판단→안전·유효 권한 확인 후 출발한다. 감속·정지 여유는 CORE 형상·지연·제동 측정에 결속한다. 기존 D-573 코드가 이 구분을 구현했다고 주장하지 않는다. 구현 시 기존 API/reference/schema에 변화가 있으면 같은 변경에서 계약·회귀시험을 함께 고친다. 본 설계는 기존 운영 기본값을 자동 변경하지 않는다.
4. **장애물과 정지.** 벽·정적 물체·동적 장애물·UNKNOWN 센서 영역은 기존 body sweep·정지 간격·IR·freshness·E-Stop 검사를 유지한다. 학습 또는 Fleet grant가 장애물 정지를 덮어쓰지 않는다. 재개는 실제 위험 해소와 관측 회복 후 기존 gate가 결정하며 무한 대기의 원인을 지우거나 임의 RESUME으로 완주를 만들지 않는다.
5. **native 연결과 신원.** D-653의 isaac-pinky-a/b를 서로 다른 CORE/CommandManager/LineFollowManager/epoch·관측 상태와 두 native articulation에 일대일 결속한다. 한 owner만 각 몸체에 명령을 적용하며 공통 simulation clock·단위·좌표·모델 identity를 기록한다. 상대 후보·이전 epoch·TTL/관측 만료는 해당 owner가 거절한다. reset은 실제 두 몸체 정지 확인 뒤 진행하며 격리 simulation만 연결한다. 실제 Fleet 서버 연결과 native bridge를 검증하지 않은 local 객체 시험은 Fleet 실행 수용이 아니다.
6. **학습 대상.** 기존 조향 gain .75/1.0/1.35/1.7만 학습한다. gain은 기존 조향 계산에 적용하며 안전 gate 이후 최종 명령에 덧곱하지 않는다. 모델·지도·신호 규칙은 정책이 바꾸지 않는다. 유효하고 신선한 카메라 target과 측정 transition만 갱신하며 camera loss·map-only 복귀·권한 실패는 유효 학습 성과가 아니다. 필수 신호/주의 정지를 지연 보상으로 벌하지 않도록 reward와 진행 측정을 검증한다. 기존 R12의 updates 0을 먼저 해결하고 정책 hash·유효 업데이트·고정 평가를 남긴다.
7. **구현 순서.** (a) 지도 표식/방향·센서·기존 모델 target 일치와 한 대 기준선, (b) CORE 횡단 서행/주의 정지 및 정상·실패 gate, (c) 실제 Fleet 순서·신선 권한·점유·진출, (d) 두 native 몸체·독립 owner 폐루프, (e) 유효 RL와 동일 조건 baseline/고정 정책 비교, (f) 독립 평가와 영상/trace 보관 순서로 진행한다. 각 단계는 실패 재현→최소 구현→원격 회귀·known_failures→bounded native 실행·실제 정지·cleanup을 통과해야 다음 단계 수용으로 올린다.
8. **완료 기준.** 최소 독립 평가 seed 3개, 0/+90/180/-90 네 시작 방향과 두 출발 순서를 포함한다. 같은 source/map/model/초기 조건/seed의 baseline과 frozen RL을 짝지어 두 로봇 각각 전체 ordered 경로와 목표 정지를 완료한다. 정상·적색·불명·stale 신호, 보행자 점유, 정적/동적 장애물, grant 상충/만료·통신 단절의 실제 안전 정지와 회복을 확인한다. 신호 위반·위험 진입·상충 grant·충돌/벽 침범·진출 차단 교착은 0이어야 한다. 오차 RMS/p95/max·조향 변동·유효 update·성공/실패·실제 속도·grant/lease/occupancy trace를 공개한다. 실제 headless Isaac 원본 영상과 모델/정책/맵/source SHA 및 독립 검증을 private 일지에 보관한다. Gazebo·ROS-SIM·실물 수용을 구분하며 timeout·teleport·camera loss·stub/mock 통과를 완주로 세지 않는다.

### Consequences

최종 완료에는 병렬 환경의 실제 시간 겹침·환경별 유효 업데이트와 heldout 개선, 두 로봇 Fleet 전체 완주 및 교통 실패 조건 0위반이 모두 필요하다. 원격 시험 PC 확보나 설계 확정만으로 실행 증거를 대신하지 않는다.

이 ADR은 사용자가 승인한 구현 목표·권한·수용 순서다. 네 신호 표시, 실제 Fleet/native 연결, 유효 카메라 RL 정책·두 대 완주 영상은 아직 구현/수용 완료가 아니다. D-606 일반 Isaac Lab readiness나 운영/실물 승격은 열지 않는다. 현재 실패를 그대로 기록하고 실제 증거가 모든 요구를 충족하기 전 완료를 선언하지 않는다.

**Related:** D-2, D-18, D-517, D-525, D-541, D-573, D-606, D-638, D-650, D-653.

### Addendum 2026-10-12 — 두 대 Gazebo 도로 증거 연결

통합 회귀에서 native 실행 파일의 628줄 초과를 확인해 기존 카메라 tick·episode admission·sampling 검증을 같은 tools/sim/isaac의 camera_checks.py로 옮긴다. 기존 run_map_rl import 이름은 같은 함수를 재노출한다. 함수 AST·안전 정지·학습 제외·샘플 주기·오류 의미는 유지하고 SDK 의존성을 추가하지 않는다. 기존 동작 회귀와 export identity로 검증하며 크기 기준을 올리지 않는다.

도로 검출기의 가로 띠 검출은 260919의 진행 방향과 나란한 횡단 줄무늬를 놓친다. 기존 D-491의 crosswalk_extent·BirdsEye를 GroundPlane이 있는 경우 재사용한다. 가로 표식 검출은 우선하며 기존 정지선·신호 판정과 CORE 정책을 변경하지 않는다. 줄무늬 치수·간격·관측된 바닥 grid가 있어야 metric 관측을 만든다. 학습된 차선 검출을 대체하는 새 모델이 아니며 실제 카메라 판정·좌표·오차 수용은 별도 확인한다. A24 첫 카메라 이미지에는 기동 시점의 pose 기록이 없어 명목 높이로 거리 정확도를 단정하지 않는다. 다음 native 시험은 안정된 frame과 odom·Gazebo pose를 함께 보관한다.

A21 runner 설정의 ENFORCED와 Fleet snapshot의 DISABLED가 일치하지 않았다. 실제 CORE 교통 endpoint의 직접 readback 전에는 ENFORCED 실행을 수용하지 않는다. 지면 투영은 기존 simulation guard가 허용하는 GAZEBO source로 연결하며 실제 shared helper의 투영 생성 회귀로 확인한다.

실제 A21에서 두 CORE·Fleet online 2/2·카메라/차선/LiDAR/odom과 CORE별 최종 publisher를 확인했으나 위치는 UNKNOWN이었다. 기존 multi_real launch는 road/observation 발행자를 시작하지 않아 ENFORCED 교통 정책에 도로 증거를 공급하지 못했다. 기존 road_observer_node를 각 namespace의 camera/front에 연결하고 declared URDF nominal 카메라 투영·map_v2_fleet 식별자를 명시한다. 기존 learned line observer는 유지한다. 도로 관측 노드가 기존 front JPEG와 raw preview를 발행하므로 단순 JPEG relay를 중복 실행하지 않는다.

이는 기존 RGB 도로 검출기 연결이며 학습된 주의 표식·보행자/신호 인식의 정확도 검증이나 네 신호 표시 구현을 대신하지 않는다. UNKNOWN 위치·신호·stale 관측·CORE 최종 권한을 완화하지 않는다. 원격 구조 시험, 실제 road evidence 수신과 preview 단일 발행, 실제 교통/주행 수용은 별도 검증한다.

### Addendum 2026-10-12 — 공유 지도 진입·진출 규칙 정합성

기존 양방향 지도는 링 진입 네 방향을 열었고 Isaac 경로도 NW·SE에서 재진입했다. 승인한 NE·SW 진입/NW·SE 진출 구조에 맞춰 원본 `lane_rules.yaml`에 기존 TurnBan 계약으로 NW의 west→ring_w 및 SE의 east→ring_e 금지를 기록한다. 두 파생 lane_graph는 생성기로 갱신하며 Fleet 지도 가져오기가 이를 보존한다. 신호 접근로 검사는 연결된 진입 중 금지된 전이를 제외한다. 도로의 양방향과 링에서 도로로 나가는 합법적 진출은 유지한다.

Gazebo camera site 설정은 ring 네 edge를 capacity 1 roundabout으로 묶고 east:rev(NE)·west:rev(SW) 접근로에 기존 sig_ring을 설정한다. 네 실제 신호 표시 연결은 별도 구현·실행 검증이 남았다. 기존 occupancy 모드의 FREE/UNKNOWN 판단과 CORE 최종 권한을 변경하지 않는다.

Isaac ordered 경로는 두 도로를 reverse 방향으로 지나 합법적인 NE·SW 진입을 사용한다. 경로 적재 시 금지 전이를 거절하며 전체 링과 두 도로를 포함한다. 이전 R17/R21의 경로와 달라졌으므로 그 수치를 새 경로의 개선 비교에 재사용하지 않는다. 같은 새 source·경로·초기 조건의 baseline과 frozen RL 재평가가 필요하다. 원격 계약 시험과 실제 Fleet 설정 readback, native 완주·교통 수용은 각각 별도 증거다.

### Addendum 2026-10-12 — 실행 분리와 Gazebo 도메인 계약 수정

사용자 요청에 따라 모델 PC의 headless Isaac은 한 대의 기존 segmentation·line_follow·CORE 조향 gain RL과 완주를 검증하고, 다른 PC의 headless Gazebo는 두 대의 독립 CORE와 실제 Fleet·신호·횡단·주의 표시·장애물 완주를 검증한다. 동일 map_v2_fleet/STL 파생을 사용하며 Isaac 한 대 결과를 두 대 Fleet 수용으로 계산하지 않는다. 병렬 RL 환경과 독립 평가 요구는 아직 미완료인 별도 증거로 유지한다.

실제 두 대 Gazebo 정지 센서 시험에서 기존 D-426 예약 범위 120..199의 domain 172가 CORE의 0..101 검증에 거절됐다. 검증용 예약·run_spec·sim 전용 watchdog 범위를 80..99로 수정하고 기존 일반 sim 난수 범위는 20..79로 분리한다. 기존 manifest를 새 범위로 몰래 재해석하지 않고 새 run을 예약한다. localhost DDS·partition·신원·포트/domain 충돌 검사를 유지한다. 실제 로봇의 40+N과 수치상 겹칠 수 있으므로 범위 자체를 장치 격리 증거로 쓰지 않는다. CORE 안전 범위와 FOREIGN_NAMESPACE 진단은 변경하지 않는다. 예약 값의 CORE/launch 수용 및 watchdog 경계·만료 시험을 함께 수행한다. 이 수정과 정지 센서 확인은 Fleet 통행권·주행·RL 완주를 증명하지 않는다.

### Addendum 2026-10-12 — 공유 바닥 시각 자산 재현

R23 실제 카메라와 소스 비교에서 Isaac의 단색 바닥과 Gazebo training-curved world의 카펫 재질 차이를 확인했다. 기존 학습 모델 pin은 동일하다. Isaac은 같은 world의 카펫 18개·기준 사각형 4개·도킹 표식 1개의 pose·크기·색상과 기존 PNG를 읽어 시각 plane을 생성한다. 검증되지 않은 parent 회전, 비정상 geometry·pose, 맵 밖이나 누락된 텍스처는 렌더 전에 거절한다. 기존 벽 collision·페인트·주의 표식 생성과 CORE·camera admission·무효 관측 학습 제외는 유지한다.

텍스처는 원래 diffuse 색을 modulation하며 [OpenUSD 공식 규격](https://openusd.org/dev/spec_usdpreviewsurface.html)에 따라 연결 형식을 선언한다. 이 변경은 renderer 사이의 픽셀 동일성이나 인식 개선을 증명하지 않는다. 기존 native ground 배경과 road_lines model Z offset 등 전체 시각 일치는 추가 확인이 필요하다. 실제 SDK 영상·카메라 관측·동일 초기 조건 baseline/frozen RL·전체 완주를 별도로 검증한다. 이 소스 변경이나 호스트 회귀 통과를 RL 성과·Fleet 통행권·교통 수용으로 계산하지 않는다.

후속 source는 같은 world의 ground RGB·100m 사각형 크기와 road_lines model의 Z 0.001m pose도 읽어 적용한다. caution·wall pose, CORE·정지·완주 판정은 유지한다. 현재 알려진 수평 SDF ground 범위만 수용하며 임의 지형이나 엔진 사이의 물리 동일성을 주장하지 않는다. RGB·크기·paint pose의 비정상 값을 거절하고 실제 SDK USD 메타데이터에서는 paint transform을 확인했다. 새 ground의 PhysX·렌더링·픽셀·전체 주행은 아직 별도 수용이 필요하다.

### Addendum 2026-10-12 — 차선 상실 종료 벌점의 실행 행동 연결

앞의 무효 관측 학습 제외는 무효 관측을 다음 state로 승인하지 않는다는 뜻으로 유지한다. 카메라 학습의 명시적 camera_lane_lost 종료에서는 해당 episode에서 마지막으로 유효 state와 함께 CORE를 통해 전달된 행동에 종료 보상을 한 번 반영한다. 다음 state는 None이며 bootstrap은 0이다. 기존의 state=None 조기 반환은 차선 상실의 실패 보상까지 누락했으므로 이를 구분한다. nonterminal·truncation·다른 종료 이유와 미실행 episode의 무효 관측 거절은 유지한다.

실행 기록은 바퀴 명령 적용 함수의 성공 반환 후 receipt가 해당 후보와 일치하고, 최종 명령이 0이 아니며 CORE 경고와 halted 상태가 없을 때만 보관한다. 단순 cmd_vel_cycle 반환은 fallback ZERO일 수 있어 증거가 아니다. 기록은 episode마다 비우고 종료 trace에 원래 frame·state·action·twist를 남긴다. 이 receipt는 명령 전달 증거이며 실제 이동이나 정책의 인과적 책임을 보장하지 않는다. 종료 벌점 연결은 camera_failure_reason이 camera_target_unavailable인 경우로 제한한다. stale·추론·scan 등 외인성 실패는 기존 실패 종료와 정지를 유지하되 조향 행동에 벌점을 연결하지 않고 원인을 trace에 남긴다. 이 벌점만으로 조향 성능 향상을 주장하지 않는다.

관측 freshness·차체 여유·CORE 최종 권한·zero와 물리 정지는 변경하지 않는다. 마지막 실행 기록은 보상 계산에만 사용하고 기억된 목표나 명령으로 재주행하지 않는다. 원격 회귀와 native 종료 보상 readback 뒤 동일 조건 baseline/frozen 정책을 비교하며, 이 수정은 병렬 학습·한 대 완주·두 대 Gazebo Fleet 수용을 대신하지 않는다.

### Addendum 2026-10-12 — 카메라 관측 단위 조향 학습

동일 source_stamp에서 physics tick마다 재탐색·Q 갱신하던 시간 단위를 수정한다. 새 유효 카메라 source_stamp에서만 bounded 조향 gain을 선택하고, 다음 유효 관측 또는 episode 종료에서 확인된 실행 구간의 measured reward를 합쳐 한 번 갱신한다. gamma0.95는 관측 구간 단위다. 현재 취득 간격은0.1 sim second이며 다른 취득 간격의 시간 의미는 별도 검증한다. 첫 관측·미실행 구간은 보상을 연결하지 않고 역행·비유한 stamp는 거절한다.

매 tick 기존 camera_tick·line_follow·CORE·freshness·장애물·정지 판단을 유지한다. gain을 유지하는 것은 관측 갱신이나 주행 허가가 아니다. ZERO와 비학습 이동의 실행 연결 구분, target 상실 종료 원인 제한과 일회성 처리를 유지한다. baseline은 gain1, eval은 탐색·Q 갱신 없이 같은 관측 경계를 따른다. camera policy schema는 isaac-camera-error-confidence/2로 구분해 이전 physics-tick 정책 복원을 거절한다. 고정 모델 revision/hash는 유지한다.

설계·시험 범위는 [관측 단위 학습 설계](../plans/2026-10-12-camera-learning-cadence-design.md)를 따른다. 이 변경의 회귀 통과는 native 재학습·Q 독립 재계산·전체 완주·병렬 RL·Fleet 교통 수용을 대신하지 않는다.
