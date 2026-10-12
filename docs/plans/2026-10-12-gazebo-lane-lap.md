# Gazebo CORE 차선추종 지도 완주

2026-10-12. 작업 브랜치 `fix/gazebo-map-lap`.

## 목표와 범위

`map_v2_fleet` / `260919 MAP FILE.STL` 계보를 보존하고 실제 CORE 차선추종과
Fleet 유한 trip으로 지도 경로를 완주한다. 사용자는 Gazebo부터 진행하고 실물 감독은
추후 확정하기로 했다. 실물 주행은 현재 실행 범위에서 제외한다.

기준 구간과 첫 수정 비교는 기존 `training-curved` 파생 지도다. 이 지도는 동쪽 S자 곡선을
강화한 훈련용이며 원본 실측 지도와 같지 않다. 이를 명시하고, 최종 지도 수용에는 원본
`map_variant=.` real profile의 유한 완주와 새 실행의 반복 확인을 별도로 요구한다.

이전 R8은 0.179107m 전진·취소·권한 해제·정지를 확인했지만 목표 소실과 기억 경로를
사용하지 않았다. 완주 증거로 대체하지 않는다. 시작 기준 소스는 commit `2e29bd118`이며
후속 후보마다 전체 source·model·map·effective profile과 실제 import/install 경로를 고정한다.
수정 전 CORE와 새 helper를 섞은 이전 구성 대신 하나의 committed snapshot을 빌드한다.

## 완료 기준

1. 선택한 로봇 한 대가 실제 Fleet 계획의 유한 경로를 실행한다. 먼저 목적지 한 구간을
   완료한 뒤 서쪽·동쪽 도로를 포함해 출발 장소로 복귀하는 1회 경로를 검증한다.
   기존 이름 있는 장소와 `via`·`repeat:false` 계약을 사용하고 생성 그래프를 손으로 고치지 않는다.
2. 카메라 관측·현재 목표·기억 경로·CORE cue·typed route context·Fleet 통행권과 실제
   최종 명령 및 odom을 같은 실행에서 기록한다. 경로 진행과 도착을 독립 Gazebo 자세와
   대조하고 실제 차체의 차선 경계·충돌 여부를 검증한다. 관측 없는 구간은 정상으로 채우지 않는다.
3. trip terminal `arrived`, 실제 출발 장소 복귀, lease 해제, CORE OFF와 마지막 명령 zero,
   기존 기준의 실제 연속 정지를 확인한다. API 성공이나 누적 거리만으로 완주를 선언하지 않는다.
4. 같은 후보의 새 초기화 실행에서 재확인한다. 실패한 실행과 변경 전 결과를 보존하고
   후보의 회귀·독립 리뷰·착지·push·CI를 구분해 기록한다.

## 반복 순서와 중단 조건

- 정규 sim 자원 gate를 통과한 격리 host/domain/partition/port에서 실행한다.
  다른 세션의 프로세스·예약·소스를 변경하지 않는다.
- 첫 구간은 실제 계획 길이를 기록하고 sim 180s·wall 300s·계획 길이와 명시한 거리 여유로
  실행을 제한한다. 거절·센서 소실·권한 소실·충돌·실제 경계 이탈에서는 즉시 정지를 요청한다.
  odom 기반 watchdog은 HTTP 응답을 기다리지 않는다. 정지 요청 거리와 최종 총거리를 나눠 기록한다.
- 실패 단계별로 runner, Perception, 목표 추출, 경로 안내, Fleet, CORE, actuator를 구분한다.
  단일 원인 가설을 재생과 실패 회귀로 고정하고 공유 로직에서 최소 수정한다.
- 현재 유효한 센서·몸체·차선·통행권 검사를 유지한다. 통과를 위해 가짜 floor 값,
  현장 walker 선언, 능력 강제 광고, E-Stop 해제 또는 별도 최종 명령 publisher를 만들지 않는다.
- 목표 소실은 직선·곡선의 current/source odom 변환과 시간·거리 예산, 새 충돌 관측의
  중단을 비교한다. 지속 전진을 위해 오래된 명령을 재사용하지 않는다.
- `speed_cap`은 현행 Fleet 계획 비용·ETA에만 쓰인다. 실행 속도는 실제 CORE profile과
  최종 명령으로 검증한다. 계획값을 실행 한도라고 주장하지 않는다.

## 증거 상태

최신 전체 소스의 첫 목적지 실행은 실패했고 안전 종료를 확인했다. commit `2e29bd118`의
7,503개 파일과 17개 ROS 패키지를 새로 빌드한 뒤 CORE02→SW 2.8649m 구간을 실행했다.
최종 이동은 0.210783m, 중심 옆거리 약 10mm, 차로 접선 대비 방향 오차는 약 +47.45°였다.
Fleet은 초기 operator pin의 `anchor_age_s=10.244`가 기존 10초 상한을 넘어 정지했다.
처음 원인으로 읽었던 `out_of_order=1`은 부수 진단이며 직접 DEGRADED 원인이 아니었다.
native odom 922개 시각은 증가했고 기억 경로가 3프레임 사용됐다. 이후 pivot·off_line·
drivable_closed를 관측했다. trip은 stopped, arrived=false다. lease 해제·OFF·실제 연속
정지·자기 프로세스/포트/lock 종료와 원래 source hash 보존을 확인했다.

독립 리뷰에서 관측의 기본 역산법칙(.08m/s, gain .8)과 실제 Pinky CORE 법칙(.10m/s,
gain 2.0)을 조합하면 명령 곡률이 목표의 두 배가 됨을 확인했다. 현재·creep·기억 경로와
Isaac 소비자가 실제 CORE 설정으로 같은 역산법칙을 사용하도록 수정 중이다. commit
`45e92d326`의 원격 수학·기억 경로·잘못된 설정 회귀 28 PASS, 기존 관측 회귀 83 PASS,
Isaac camera 회귀 82 PASS다. 각 known_failures 결과는 NEW 0이다. native camera와
CORE의 HOME 차이에 따른 운영자 설정 전달은 기존 status-inputs handover로 구현했다.
commit `077d2e475`는 유효 법칙 4개와 robot/PID metadata만 기존 0644 원자 기록에 넣고,
native camera가 소유자·identity·범위·UTC 신선도를 검증한다. 법칙/PID 변경·누락·오래된
입력에는 이전 조향과 기억 경로를 지우고 관측을 거절한다. CORE API 시작 전에 즉시
기록하고 이후 기존 1Hz 기록을 유지한다. 쓰기 실패의 기존 정책과 최대 3초 freshness
창은 유지되므로 실패 상황에서도 이전 payload를 항상 차단한다고 주장하지 않는다.
전체 관측 회귀 3,140 PASS/110 SKIP, 최종 startup·handover 관련 183 PASS/NEW 0,
독립 SOURCE APPROVE다. 실제 장치 handover와 재시작은 아직 실행하지 않았다.

긴 Fleet trip에는 지속적으로 유효한 지도 자세가 필요하다. 실제 overhead 영상·로봇 식별·
accepted Vision 공급은 현재 Gazebo 구성에 없다. 기존 `map_pose_port` 주입을 이용하는
명시적 SIM-only native-Gazebo 위치 adapter를 검토한다. 원본 좌표·sim stamp·wall receipt,
map/run/source/domain/partition/frame 결속과 epoch·freshness를 검증하며, authority에는
실제 CORE snapshot의 UTC odom stamp를 유지한다. trip·차로 감시·지도 자세 조회·교차로
판단은 같은 위치 provider를 사용하고 camera ingest·operator pin·teach·formation에는
SIM 위치를 자동 확장하지 않는다. 새 공개 pose 입력 API나 주기 pin, TTL 확대는 사용하지 않는다.

SIM 위치 후보 `34b7856198`은 독립 SOURCE APPROVE와 정상 원격 115 PASS/NEW 0이다.
최신 main과 조향법칙·native handover·SIM 위치 후보를 통합한 전체 소스로 새 빌드와 구간 시험을 진행한다.
사용자는 Gazebo부터 진행하고 실물 감독은 추후 확정하기로 했다. 지도 완주와 새 후보의 실물 수용은 미확인이다.

원본 native receipt를 보관 후 join 시각과 구분한 `ba37decc42`는 독립 SOURCE 승인,
native 55 PASS와 소비자 198 PASS/NEW 0이다. 실제 runner의 clock join도 별도 SOURCE 승인됐다.
넓은 통합 회귀 `94aed4a52e`는 14,168 PASS/816 SKIP와 구조 검사 2 NEW로 끝났다.
`c43f21105`는 Perception의 CORE 설정 import를 제거하고 Gazebo launch에서 4개 읽기 전용
법칙 값만 전달한다. 보조 reader를 관측 배선 계층으로 옮긴 후 관련·구조 회귀 117 PASS/NEW 0이다.
전체 통합 snapshot의 실제 빌드·관측 값 readback·주행은 이어 확인한다. 차체 경계의 샘플 검증은
기존 2mm paint raster와 NOMINAL_BODY를 사용하며, 원본 contact와 연속 swept 증거는 별도로 구분한다.

## 통합 후보 실제 실행

- `e6d0fe12ba`: 최종 통합 원격 219 PASS/NEW 0, 전체 소스 7,526 파일 고정과 17 ROS 패키지
  fresh build 13.5초를 확인했다. 실행 자원 기준을 통과한 AI PC에서만 Gazebo를 실행했다.
- Leg2는 출발 전 전체 ROS 파라미터 조회가 초기화되지 않은 선택 `route`에서 빈 응답을 반환해
  거절됐다. 이동 0m와 안전 종료를 확인했다. 설치된 Jazzy parameter service와 CLI 소스 및 실제
  경고를 대조했으며 제품 설정을 바꾸지 않고 네 필수 값의 직접 조회로 실행기를 수정했다.
- Leg3는 같은 소스·설치 해시와 실제 두 observer의 `.1/.1/2/.35` 조회, CORE 프로세스의
  설정 경로·domain, native SIM 위치 LOCALIZED, Fleet plan/start 200과 실제 lease를 확인했다.
  실제 이동은 0.341412m이고 terminal은 `stopped/stall`, `arrived=false`다.
- 마지막 양의 native 명령은 CORE 후보와 정확히 같은 `.0369939m/s/.117409rad/s`였으며
  곡률은 3.173743/m이다. 당시 카메라는 current turn-left였고 교통은 clear-road/scale 1이다.
  최종 명령은 0이 됐지만 CORE 후보는 이후에도 양수였다. 목표 소실을 첫 정지 원인으로
  확정하지 않는다. 최종 `blocked=true`의 전이 시각과 full scan은 기록되지 않아 직접 원인은 미확정이다.
- selected02의 pose UNKNOWN은 Fleet stall/OFF 뒤에 나타났다. 원본 native 입력은 신선했고
  소비자가 더 이상 갱신하지 않은 CORE snapshot과의 시간 차가 1.2초를 넘었다. 이 현상은
  이번 stall의 선행 원인이 아니다. 다음 runner는 두 CORE의 실제 snapshot 읽기를 2Hz로 유지한다.
- OFF·lease 해제·실제 연속 정지·futures 종료·자기 프로세스/포트/lock 종료와 소스 보존을 확인했다.
  1,417개 몸체 샘플의 paint/wall/map-bounds/other-circle 겹침은 0이지만 연속 swept/contact 수용은 아니다.
- 다음 진단은 같은 제품 후보에서 hazard 전이, full scan, 기존 `safety/motion_limits` 원문을 기록한다.
  guard 임계값·CORE 명령 권한·지도·source stamp는 바꾸지 않는다. 새 runner의 독립 리뷰 후
  한 번의 제한 구간을 재실행해 최초 최종 명령 거절을 확인한다. 지도 완주는 계속 미확인이다.

## Leg4: 전방 제한과 곡선 후보의 실제 정지

- Leg4도 전체 소스 `e6d0fe12ba`와 같은 설치 해시를 사용했다. AI PC의 정상 SIM 자원
  기준을 충족했고, 두 로봇의 실제 CORE snapshot을 2Hz로 읽어 위치를 유지했다.
  LOCALIZED 갱신은 각각 205회이며 실패와 종료 후 남은 작업은 0이다.
- 이동 0.311955m 후 `stopped/stall`, `arrived=false`다. 전방 blocked 전이 시각은
  monotonic 40357.751841, 최초 native zero는 40357.757975다. Fleet stall 확인은
  그보다 약 19초 뒤다. 현재 카메라 관측이 유지되는 동안 전방 제한이 먼저 발생했다.
- 실제 `safety/motion_limits`의 전방 거리는 0.130544m, 정지 기준은 0.14905m이다.
  회전 간격은 허용됐지만 양의 선속도를 가진 곡선 후보에서 선속도만 0으로 만들면
  검사한 궤적이 바뀐다. CORE의 기존 곡률 보존 제한이 최종 두 축을 0으로 만든다.
  원본 scan 640개와 실제 lidar TF를 소스에 재생한 전방 거리는 발행값과 일치했다.
  재생은 분류 근거이며 내부 evaluator가 소비한 개별 snapshot 식별 증거는 아니다.
- OFF 200, lease 해제, 실제 연속 정지, 작업 종료, 자기 프로세스·포트·lock 종료와
  소스·설치 해시 보존을 확인했다. 원본 지도 완주·연속 swept/contact·실물 수용은 미확인이다.
- 비교 A의 초기 기록 재생은 실제 관측 polyline과 반경 0.12m의 교점 또는 첫 관측점을
  목표로 선택한다. 이는 기존 helper의 arc station·row band 규칙에서 lookahead 값만
  바꾸는 것과 다르다. 이 대안은 초기 직선에서 과도한 곡률을 만들고 코너에서는
  오히려 회전 예견을 없애므로 채택하지 않는다.
  비교 B의 기존 CORE REALIGN 회전은 인증된 turn spot과 회전 증거가 필요하다.
  `can_rotate=true`만으로 차선 안의 회전을 승인하지 않는다. 안전 기준은 유지한다.

## 내장 센서 노드 이름 수정

`47ace984f2`는 CORE의 전역 ROS 이름 remap이 내장 SafetyNode 이름까지 덮는 문제를
수정했다. namespace가 명시된 sensor-only 노드에만 자체 이름 remap을 적용하고,
CORE가 실제 `use_sim_time`을 명시 전달한다. 기존 namespace·topic remap·독립 센서
실행 의미는 유지한다. 정상 원격 자원에서 실제 Jazzy 실행을 포함한 115 PASS/NEW 0과
독립 SOURCE 승인을 확인했다. Leg4의 실행 소스에는 이 수정이 없으며 수정 후 실제
Gazebo graph와 주행 readback은 다음 후보에서 확인한다.

## Leg5: 원본 지도와 흰 벽의 정지선 오인식

- `8ce7a7abc` 전체 7,528개 소스를 새로 빌드했다. 실제 17개 ROS 패키지 빌드와
  원본 `map_variant=.`의 world·graph·Fleet import·native binding 결속을 확인했다.
  두 namespace 각각 CORE 1개·safety_node 1개, 실제 clock·sensor subscription,
  `.1/.1/2/.35` observer 법칙과 원본 graph hash를 출발 전에 확인했다.
- 이동은 0m, 최종 Fleet `stopped/stall`이다. 조향 후보가 양수인 동안 실제 전방 거리는
  약 0.44m로 정지 기준 0.14905m보다 컸고 hazard는 false였다. 교통 정책은 실제
  `stop_distance_unavailable` HOLD를 89회 반환했다. 카메라 차선 관측과 두 위치는
  유지됐다. 각각 173회의 LOCALIZED 갱신, 종료 후 남은 작업 0을 확인했다.
- 실제 RGB 센서 영상을 BGR로 복원한 lossless PNG에서 밝은 가로 그룹은 `[0,122]`다.
  흰 벽 전체가 정지선 후보가 됐고 평균행 61, confidence 0.952667683을 정확 재현했다.
  유효 카메라 지평선은 80.424이므로 평균행의 거리 계산은 None이다. 후보 하단 122는
  지평선 아래이므로 후보 전체가 지평선 위라는 설명은 틀리다. 주행 전후 네 기록 영상에서
  같은 결과를 확인했다. 첫 내부 소비 snapshot 식별과는 별도인 기록 영상 재생 증거다.
- 단순 그룹 삭제나 지평선 아래 crop은 채택하지 않는다. 전자는 벽에 연결된 실제 STOP을
  지울 수 있고 후자는 남은 벽을 다시 정지선으로 만든다. 기존 `floor_white_mask`의
  벽 접촉·바닥 페인트 분리를 우선 비교한다. 모호한 STOP의 거리 None/HOLD는 유지한다.
- OFF 200·lease 해제·실제 정지·작업 종료·자기 프로세스/포트/lock 종료와
  소스·설치 해시 보존을 확인했다. 원본 지도 완주와 실물 수용은 계속 미확인이다.

## Leg6: 거리 복원 뒤 벽 오인식과 궤적 문제

- 전체 소스 `72c525516231af3699fbef2a54e12927238c3578`을 새로 빌드하고
  원본 `map_variant=.`에서 0.346443m 이동했다. Fleet terminal은 `stopped/stall`,
  완주와 도착은 false다. 거리 None에 의한 HOLD는 0회지만 벽 오인식은 남아 있다.
- road stamp 43.375의 STOP confidence 0.415625는 실제 traffic 기준 0.5보다 낮다.
  수신 monotonic 47905.872497 뒤 최초 native zero는 47905.964162이고,
  첫 API HOLD 확인은 47906.079191이다. 직전 전방 거리 0.248916m는 기존 정지
  기준 0.14905m보다 크며 hazard는 false다. 원본 정책 함수 재생은 같은 관측에서
  `stop_line_low_confidence` HOLD를 반환한다. 내부 소비 snapshot 식별 증거는 아니다.
- 기록 사진에서 선택 그룹 `[136,145]`는 오른쪽 흰 벽의 하단으로 보인다.
  이는 영상 검토에 따른 추론이며 독립 정답으로 라벨링한 실제 바닥 STOP 증거가 아니다.
  카메라 관측 392회는 모두 `drivable_centre`, held 0회다. 목표 소실이나 이전 목표
  유지가 이번 최초 정지의 원인이라는 주장은 하지 않는다.
- 접근 중 교통 정책은 선속도만 감소시킨다. 마지막 양의 후보는
  `.037539385m/s / .073772270rad/s`, native는 `.024294115m/s / .073772270rad/s`다.
  이는 당시 scale 0.647163과 일치한다. 기존 body-stop의 arc-family 안전 검사와
  차선 추종 품질은 별개다. paint 겹침에 대한 인과 기여는 추가 비교가 필요하다.
- 2mm 래스터에서 selected02 차체 paint 겹침은 1,534개 샘플 중 427개다.
  정지 후 중복 샘플도 포함되므로 독립 사건 427건으로 세지 않는다. wall·map 밖·
  other-circle 겹침은 0이지만 연속 swept/contact와 도로 내부 준수 증거는 아니다.
  최대 native 선속도는 0.081939m/s다. Fleet 계획의 0.08m/s는 실행 cap이 아니므로
  0.08m/s 이하 실행을 증명하지 못한다. 실제 CORE 한도 위반과는 구분한다.
- 실제 원본 Image 44개를 2Hz로 보존했고 raw/PNG 해시 불일치와 truncation은 0이다.
  두 로봇 각각 LOCALIZED 228회, 종료 시 남은 작업과 오류 0, OFF·lease 종료·
  연속 정지·자기 프로세스/포트/lock 종료와 소스 해시 보존을 확인했다.
- 다음 비교는 기존 바닥 마스크와 실제 시점별 관측·주행궤적의 기하 일관성이다.
  같은 색 벽과 연결된 실제 STOP을 지우는 마스크 반례를 유지한다. confidence 기준,
  unknown HOLD, 안전 거리, 최종 명령 권한은 바꾸지 않는다. 추가 주행 전에
  오인식 분리 근거와 차선 궤적·속도 한계의 독립 검토가 필요하다.

## Leg6 기록 비교와 후속 수정 후보

- A: 기존 `floor_white_mask`는 실제 벽 후보를 지우지만 같은 색 벽과 연결된 STOP,
  얇은 지평선 주변 STOP까지 지우는 반례가 있다. 후보 삭제 판단에 채택하지 않는다.
- B: 원본 44개 영상의 해시와 실제 camera TF·odom을 검증한 두 시점 바닥 warp를
  정상 원격 자원에서 비교했다. 31→32초의 바닥 페인트 밝기 잔차 중앙값은 0,
  벽 바닥은 1이며 40→41초의 벽 바닥도 0이다. 정지 시점과 동일색 attached STOP
  합성 반례도 잔차 0이다. 평가 ROI는 사람이 지정한 진단 영역이며 실제 STOP 정답이나
  운영 임계값이 아니다. 벽 본체는 공통 바닥 관측 영역 밖이므로 그 영역의 성공을
  주장하지 않는다. 바닥 warp 잔차만으로 벽과 STOP을 분리하는 안도 채택하지 않는다.
- C: 실제 접근 감속은 첫 paint 겹침보다 약 11.20 wall초 먼저 시작했다.
  시각 37.209의 기록 명령값 대응에서 scale 0.487369이며 후보 곡률은 3.783308/m,
  native 곡률은 7.762720/m이다. 같은 실제 자세와 같은 0–12cm 진행 거리의 2mm
  래스터 비교에서 후보의 첫 paint 겹침은 8.8cm, native는 0.4cm다. 후보도 끝내
  paint와 겹치므로 감속만을 유일 원인으로 부르지 않는다. 내부 소비 식별,
  폐루프 반사실 실행과 연속 swept/contact 수용 증거도 아니다.
- 최소 수정 후보는 움직이는 차선 후보의 교통 감속에서 두 축을 같은 비율로 줄이는
  것이다. 기존 순수 회전, HOLD, evidence revision, 최종 CORE 권한을 유지하고
  관련 계약과 실패 회귀를 먼저 고정한다. 벽 의미 인식과 전체 차선 품질은 따로 남는다.
- 실제 고정 모델 `lane-seg-20261010-ede0ae96`의 manifest·ONNX 해시는 Leg6 기록과
  일치했다. 클래스는 background, lane_left/right, crosswalk, speed_bump, drivable이며
  STOP와 wall은 없다. drivable은 차선을 넘지 않고 로봇과 연결되는 바닥으로 선언돼 있고
  `road_surface/1` 의미 선언은 없다. camera provenance도 provisional이다.
  이 모델의 background나 drivable 부재를 STOP 부재 또는 벽의 의미 증거로 승격하지 않는다.
