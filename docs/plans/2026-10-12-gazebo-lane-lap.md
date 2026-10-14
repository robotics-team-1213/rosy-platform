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

- 전체 소스 `72c525516`을 새로 빌드하고
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

## Leg7: 곡률 수정 후 전방 거리 정지

- 통합 소스 `a94b024fb` 전체 7,553개 파일과 17개 새 빌드 패키지를 원본 지도에
  결속했다. 정상 AI PC 자원에서 0.319664m 이동했고 Fleet는 `stopped/stall`로
  종료했다. APPROACH 255회, FOLLOW 18회, HOLD 0회다. held 0회이며 현재
  centre/turn_left 관측과 두 로봇의 LOCALIZED 각 260회 갱신이 유지됐다.
- D-735 적용 후 기록 후보/native 곡률비 중앙값은 1이다. 이는 HTTP 수신 시각을
  대응한 진단이며 동일 내부 소비 tick 증거가 아니다. 공유 정책 차체의 사각형과
  회전 원 교집합을 사용한 2mm 래스터에서 selected02 paint 겹침은 1,736개
  샘플 중 0이다. Leg6의 427개도 같은 형상으로 계산했다. Gazebo collision box와
  정책 차체는 다르며 연속 swept/contact 및 전체 지도 수용은 증명하지 않았다.
- 첫 전방 차단 시 거리 0.139323m, 같은 실행 중 해제 시 0.194002m,
  마지막 차단 시 0.145133m다. 실제 SDK stop/clear는 0.14905/0.17905m다.
  마지막 양의 명령 뒤 blocked가 발생하고 최종 zero가 뒤따랐다. cliff/tilt/pickup은
  false이며 traffic은 APPROACH였다. 현재 목표 소실이 직접 원인이라는 근거는 없다.
- 원본 640개 scan beam과 실제 LiDAR TF를 동결 소스로 재생해 위 세 전방 거리의
  오차 0을 확인했다. 실제 필터는 5세대 중앙값·1.5Hz다. 초기 0.8초 이전 기록과
  일부 scan 세대가 없으므로 전체 필터 소비 이력은 동일 재현하지 못했다.
  후반 필터 출력 최대 오차 약 1.3mm와 raw 즉시 정지 재현을 구분한다.
- 원본 영상 58개의 해시 불일치·truncation은 0이다. OFF·lease 종료·정지 확인·
  pending 작업 종료·자기 프로세스/포트/lock 종료, 전체 소스와 설치 해시 보존을
  확인했다. 이번 실행도 원본 지도 완주와 실물 수용은 false다.
- 차선 법칙은 `.1/.1/2/.35`지만 모든 명령 모드를 포함하는 실제 SDK 최대속도는
  0.2m/s다. 이 보수적 정지 거리는 기존 안전 계약이며 오류라고 단정하지 않는다.
  다음 비교는 SIM 전용 profile과 manual/fleet 한도를 모두 0.1m/s로 제한한다.
  실제 SpeedLimits·CommandManager·SDK profile 갱신에서 양방향 출력 제한,
  E-stop zero, 기존 수식의 stop/clear 0.10405/0.13405m를 먼저 확인한다.
  차체·여유 거리·지연·감속도·모델·차선 법칙은 유지하며 임계값만 덮어쓰지 않는다.
- 새 한도로 같은 구간을 통과해야 속도 envelope의 기여를 인정한다. 더 작은 거리에서
  다시 차단되거나 다른 HOLD로 멈추면 벽 접근 궤적·벽/STOP 오인식 등을 계속 조사한다.
  이전 관측과 주행 이력은 현재 센서 안전 정지의 해제 권한이 아니다.
- 통합 원격 시험은 제품이 동일한 병합 소스에서 8,104 PASS/457 SKIP,
  3,718 PASS/113 SKIP였다. 후자는 공개 문서 긴 해시 검사 신규 실패 1개를 포함했고
  `a94b024fb`에서 문서만 수정했다. 연결 복구 후 미완료 Fleet 등은 4,597 PASS/246
  SKIP, 수정 검증은 196 PASS로 끝났고 각각 NEW 0이다. GitHub CI와 착지·푸시는 별도다.

## Leg8: 전체 0.1m/s 구성 비교와 회전 여유 정지

- `ab29002f6` 전체 7,553개 소스와 새 17개 설치 패키지를 사용했다. SIM 전용
  복사 profile의 max_linear_velocity, CORE safety.manual_linear/fleet_linear만
  0.1m/s로 맞췄다. 실제 loader의 절대 robot.profile 경로와 파일 해시, API의
  max/manual 및 base/trip 한도, SDK의 max 0.1·angular 0.8과 stop/clear
  0.10405/0.13405m를 정지 점검과 주행 전 점검에서 각각 확인했다.
  별도 Fleet 개별 한도 API 필드는 없으므로 설정 해시 결속과 실제 전체 한도를 구분한다.
- 정지 점검은 이동·주행 요청·양쪽 명령 0으로 종료했다. 새 주행은 정상 AI 자원
  22.0 cores/8.3GiB에서 한 회차만 수행했다. 26.01 sim초에 0.360837m 이동하고
  `stopped/stall`로 종료했다. Leg7보다 0.041174m 더 갔지만 첫 구간을 통과하지 못했다.
  따라서 속도 envelope만으로 완주 문제가 해결된다는 가설은 지지하지 않는다.
- 마지막 양의 native 명령은 monotonic 56057.257350이다. 그 뒤 limits
  56057.329256은 front 0.138966m > stop 0.10405m, blocked false,
  can_rotate false였고 native zero는 56057.332345에 나왔다. 후속 blocked true는
  56057.538624이며 front 0.101999m다. 최종 zero 직전 회전 여유 거절과 뒤의
  전방 차단을 구분하며 정확한 내부 소비 tick을 증명했다고 주장하지 않는다.
- 원본 55.7초 scan·TF 재생에서 front 오차 0과 오른쪽 점
  `(0.040645,-0.074618)m`, 중심 거리 0.084970m를 재현했다. 기존 회전 원과 여유
  0.09257m 안에 들어온다는 SOURCE 판정은 can_rotate false를 뒷받침한다.
  이후 다섯 전방 차단 거리도 원본 scan 재생 오차 0이다. 현재 정지 후 거리
  0.113902m는 최초 차단 거리와 다르며 clear보다 작아 유지되는 상태다.
- 카메라 centre 275·turn_left 156·held 0, traffic APPROACH 228·FOLLOW 21·
  HOLD 0, 두 로봇 LOCALIZED 각 252회다. 원본 영상 54개의 해시·truncation 이상은
  0이다. 정책 차체 paint 겹침은 1,691개 샘플 중 0이지만 연속 주행·접촉·도로 내부
  수용은 아니다. OFF·lease·정지·pending 종료와 자기 프로세스/포트/lock 종료,
  소스 7,553개와 설치 1,912개 해시 보존을 확인했다.
- 정상 원격 자원의 고정 장면 비교에서는 현재 곡률로 계속 가면 약 10cm 뒤 paint와
  겹치는 예측이 나왔다. 폐루프 접촉 증거가 아니다. 짧은 0.15m 목표가 이 장면에는
  도움이 되지만 Leg7의 다른 장면에서는 벽에 접근하는 반례가 있어 무조건 단축하지 않는다.
  frame-border 출구 목표가 곡선 변화에도 거의 고정되는 현상은 후속 검토 후보다.
- 동결 URDF의 LiDAR 잡음은 gaussian mean 0/stddev 0.02다.
  [SDFormat 명세](https://sdformat.org/spec/1.11/sensor/)의 stddev는 Gaussian
  표준편차이며 오차 상한이 아니다. 원본 측정점과 실제 world·TF·pose의 예상 ray
  거리를 대조해 잡음의 기여를 조사한다. 센서 잡음 축소나 안전 거절 해제는 수행하지 않았다.

## Leg8 센서 재생과 정지 상태의 빔 위상 비교 설계

- 실제 TF·IMU roll/pitch·odom 높이와 GPU가 읽는 visual geometry를 사용해 두 원본
  scan을 재생했다. 55.7초의 회전 거절 점은 원래 북쪽 벽 거리 0.157649m보다
  0.063357m 짧고, 55.8초의 후속 전방 차단 점은 0.059306m 짧다.
  각각 설정된 잡음의 약 -3.17/-2.97 표준편차다. pose 대응은 -8/-6ms이며
  roll/pitch는 4.5e-8rad 이하다. 내부 소비 pose와 RNG 원인을 완전히 증명한 것은 아니다.
- GPU LiDAR는 collision 대신 visual geometry를 읽는다.
  [Gazebo sensors 8 원문](https://github.com/gazebosim/gz-sensors/blob/gz-sensors8/include/gz/sensors/GpuLidarSensor.hh)에
  근거해 벽·테이프·메시와 두 로봇의 visual을 포함했다. 근접 점에 대해 실제 최초
  visual hit는 북쪽 벽 y=0.625m이며 원본 range의 점은 그 안쪽이다.
- 전체 640개 잔차의 표준편차는 약 0.051/0.050m로 설정 0.02m와 다르다.
  80/400/560번 빔에는 두 scan 모두 약 0.37/-1.0/0.52m의 큰 오차가 있고 이웃은
  정상 벽 거리다. 이 번호를 사후 제외한 637개는 약 0.0205/0.0207m지만,
  이 제외는 진단이며 운영 입력에서 빔을 삭제하거나 전체 정상 판정으로 세지 않는다.
- 설치된 gz-rendering 8.2.3의
  [Ogre2GpuRays](https://raw.githubusercontent.com/gazebosim/gz-rendering/gz-rendering8_8.2.3/ogre2/src/Ogre2GpuRays.cc)는
  cube-face UV를 생성하고, OgreNext 2.3.3의
  [TextureUnitState](https://raw.githubusercontent.com/OGRECave/ogre-next/v2.3.3/OgreMain/src/OgreTextureUnitState.cpp)는
  기본 addressing을 WRAP으로 지정한다. 설치 material에 addressing override가 없다.
  정확한 소스 계산에서 80/240/400/560번의 float32 UV=1이 반대 경계로 돌아가는
  가설을 재생했다. 그 반대 경계의 예상 거리와 원본 값은 모두 ±2 표준편차 안이다.
  실제 GPU sampler state의 직접 readback이나 런타임 원인 확정은 아직 아니다.
- 비교 A는 원래 640개 grid, B는 반빔 위상의 min=-pi+pi/640,
  max=pi-pi/640이다. 둘 다 간격 2pi/640·640개·전체 원주·중복 방향 없음을 유지한다.
  원본 world·두 로봇 geometry와 동일 정지 자세, 잡음 0.02를 유지하고 CORE와
  주행 명령 발행자를 실행하지 않는다. 실물·설치 vendor 파일을 변경하지 않는다.
- 각 비교의 생성 SDF 해시·원본 자산 해시·실제 TF/자세·버전·정상 SIM 자원과
  Gazebo raw↔ROS의 같은 header/range 대응을 기록한다. 모든 빔과 nonfinite 값을
  보존하며 각 grid의 실제 각도로 visual ray 예상값을 다시 계산한다. 단일 scan의
  range 일치를 수용 기준으로 삼지 않고 반복되는 고정 번호 오차를 비교한다.
  정지 상태의 센서 생성 진단이며 지도 완주·차선 품질·실물 수용을 대신하지 않는다.

## 정지 상태의 두 빔 위상 비교 결과

- 동결 source ab29002f6과 기존 설치 전체를 재검증하고 원본/반빔 설정을 각각
  10.098 sim초 수집했다. 각 설정은 Gazebo 102개·ROS 102개 동일 header에서
  640개 거리와 강도, 각도·범위·frame의 float32 값이 전부 일치했다.
  독립 원본 재검산에서도 같은 결과이며 양쪽 scan/ROS 도착 시각 역행·중복은 0이다.
- 실제 world의 `Pose_V`로 두 정지 모델의 이름·고유 ID·위치·전체 quaternion을
  전후 검증했다. 원본 LaserScan의 `world_pose` 필드는 센서 로컬 자세로 보존하고,
  실제 모델 world 자세와 생성 SDF의 로컬 센서 자세로 계산한 world 자세를 구분했다.
  CORE·Fleet·주행 명령은 실행하지 않았다. 두 경우 종료와 residual 0,
  source 7,553개·설치 1,912개 해시 이상 0을 확인했다.
- 고정 번호의 거리 중앙값은 원본→반빔에서 80번 1.100661→0.724217m,
  400번 0.157594→1.087490m, 560번 0.718196→0.157777m다.
  원본의 큰 고정 오차가 반빔에서 줄어드는 근거다. 실제 각도별 전체 visual ray와
  원본 안전 판정의 반복 비교를 마친 뒤 Gazebo 설정 후보를 검증한다.
- Leg8 최초 회전 거절을 뒷받침한 547번은 위 고정 번호와 다르다. 원본 정지
  비교의 중앙값 0.152634m·표준편차 0.020117m는 잡음을 포함한다.
  빔 위상 개선을 최초 정지·목표 궤적·지도 완주의 해결로 동일시하지 않는다.
- 이전 수집 실패 세 건은 기록을 보존했다. 센서 로컬 자세를 world로 가정한 오류,
  CLI 자세 표시의 반올림 오차, 정확한 100ms 배수를 가정한 시간 간격 검증이다.
  마지막 경우 처음 98ms 한 번과 이후 100ms 100번을 실제로 기록했다.
  [Gazebo Sensor 구현](https://raw.githubusercontent.com/gazebosim/gz-sensors/gz-sensors8_8.2.2/src/Sensor.cc)은
  예약 시각 이후 실제 업데이트 시각으로 발행한다. 명목 10Hz 설정과 실제 시각을
  구분하고 충분한 동일 header 수집을 유지했다. 제품의 신선도·안전 기준은 바꾸지 않았다.

- 후속 정상 자원의 전체 visual ray 분석에서 잔차 표준편차는 원본 0.051153m,
  반빔 0.020229m다. 고정 빔의 잔차는 80번 +0.3824→+0.0020m,
  400번 -0.9761→-0.0074m, 560번 +0.5586→-0.0014m로 줄었다.
  원본 `scan_geometry`의 회전 공간 거절 재생은 7/102→11/102회이며
  실제 SDK worker 실행·최종 명령 수용은 아니다. 잡음과 회전 여유 문제는 남는다.
- Gazebo 센서 입력 후보로 두 각도만 반빔 이동하고, 기존 비중복 한 바퀴 시험에
  float32 cubemap face 경계 회귀를 추가한다. 정상 모델 PC에서 기존 grid의
  UV=1을 TDD RED로 확인했다. 원격 GREEN·독립 SOURCE 리뷰·새 전체 동결
  source/install 빌드·원본 첫 구간 재주행을 완료하기 전 실행 수용으로 세지 않는다.
  다음 주행의 회전 거절은 실제 후보 궤적과 기존 안전 계약으로 따로 조사한다.

## 2026-10-13 · 새 빔 위상 Leg9와 안전 정책 실패 진단

- c0bb0393c의 독립 SOURCE 승인과 정상 원격 610 PASS·7 SKIP·14 subtests·NEW 0을 확인했다. 전체 동결 소스의 17개 새 패키지와 source 7553·install 2726 파일 해시, 실제 640빔 halfphase, SDK 프로필·CORE 상한·native pose 계보를 새 정지 점검에서 확인했다.
- 같은 원본 지도 Leg9는 0.286048511 m 진행 뒤 `control:policy_failed`로 E-stop이 걸렸다. 최초 zero는 sim 43.125초이며 직전 compiled limits는 회전 허용과 front 0.204754m를 표시했다. 이전 Leg8의 회전 공간 거절과 같은 원인이라고 단정하지 않는다. Fleet는 E-stop으로 lease를 잃고 종료했으며 OFF·정지·프로세스 종료·전체 해시 보존을 확인했다. 지도 도착은 false다.
- 현재 SDK의 관측 누락·요청보다 미래인 관측·만료·평가 중 교체는 None이며 CORE는 이를 ValueError로 바꾼다. 실제 evaluator 예외도 같은 policy_failed로 처리되므로 기존 기록만으로 정확한 가지를 확정할 수 없다. probe 수신 시각은 SDK 내부 window 유효성의 증거가 아니다.
- 36f9fee29의 정상 원격 RED는 진단 회귀 6 NEW를 확인했다. 4d20dbc0d는 SDK의 정확한 평가 window를 스레드별로 기록하고, CORE 첫 예외·요청을 보관해 기존 writer 이후 announce_pending에서 한 번 출력한다. 단일 명령 타이머의 직렬 실행을 전제로 하며, 로깅 실패는 이후 zero와 알림을 방해하지 않는다. 독립 SOURCE 승인과 정상 원격 관련 회귀 terminal 0·NEW 0을 확인했다.
- TTL·clock·동작 한도·None 반환·E-stop·EMERGENCY 조건은 바꾸지 않았다. 새 전체 source/install 빌드와 정지 점검을 마친 뒤 새 실행에서 원인을 재현한다. Leg9 E-stop 해제·기존 실행 재출발·물리 주행은 수행하지 않는다. 전체 지도 완주와 독립 반복 수용은 여전히 미완료다.

## 2026-10-13 · Leg10 종료와 두 정지 원인의 분리

- 314e06aca의 최종 구조·문서 회귀 239 PASS·NEW 0과 독립 재판정을 확인했다. Git archive의 줄끝 변환 시도 두 건을 보존하고, 같은 커밋의 원본 blob으로 채운 전체 동결본 7553파일의 바이트 일치와 SHA를 검증했다. 새 설치 17패키지·2726파일, 양 로봇 0 명령·이동 0·실제 640빔·SDK/CORE 법칙·원본 STL 계보·CORE 단독 최종 publisher·종료5조건을 정지 점검에서 확인했다.
- Leg10 한 회차는 0.366485589 m 이동 뒤 `obstacle_ahead`로 종료했다. 실제 CORE는 `HOLD`, body gap 0.0094368m가 stop gap 0.0214m보다 작았고 감독 runner가 OFF/cancel했다. 정해진 거리·시간 예산 이전 정지이며 지도 도착은 false다.
- 최초 zero sim 47.766초 뒤에는 양의 명령이 다시 나왔다. 최종 zero는 54.768초이며 직전 limits는 blocked true·can_rotate false였다. 두 시점을 같은 정지 사건으로 묶지 않는다. 이번 정책 예외 로그·E-stop은 0건이며 이전 Leg9 None/예외 원인이 해결됐다는 증거는 아니다.
- 실제 camera PNG 52개·raw scan 522개·ExpectedPath live 254/held 2/dropped 154/None 13을 확보했다. sampled native pose의 paint/wall/outside/other overlap은 0이지만 연속 접촉·전체 미래 몸 쓸기 수용을 뜻하지 않는다. 종료5조건·OFF·lease 해제·잔존 프로세스 0·포트 닫힘·source/install 해시 일치를 확인했다. 추가 회차는 실행하지 않았다.
- 다음 독립 분석은 임계 빔과 실제 visual ray의 차이, 현재 카메라 목표의 곡률과 관측 도로 경계/벽의 관계를 분리한다. 현재 관측이 거절한 경로를 기억으로 되살리거나, 모든 경우에 짧은 목표를 강제하거나, 안전 빔·margin·hysteresis를 제거하지 않는다.
- 자원 예약 생성 전 목록 조회가 실패한 상태에서 파일을 정리한 절차 오류를 원본 ship receipt에 보존했다. 파일 소유권을 사후 추정으로 확정하지 않으며 다음 정리는 직접 소유 증거가 있을 때만 수행한다. 빌드와 각 실행의 실제 정상 자원 판정은 별도 기록이다.

### 임계 빔·직선 방향·후보 검증

정상 원격의 전체 640빔 SOURCE 재생에서 전방 거리는 실제 SDK 게시값과 두 구간 모두 일치했다. 최초 zero 전 임계 582번은 raw 0.118606m / 명목 visual 벽 교차 0.186310m이며 잔차 -0.067704m(-3.385σ)다. 최종 zero 전 568번은 0.101853m / 0.159249m, 잔차 -0.057396m(-2.870σ)다. 전체 잔차 표준편차는 0.019783/0.019881m로 선언 σ=0.02와 일관된다. 입력은 실제 scan/TF와 2/6ms 인접 native pose이며 같은 pose stamp의 accepted LOCALIZED join도 확인했다. GPU 정밀도·움직이는 바퀴 위상·sensor yaw 직렬화 오차는 미모델이며 정확한 소비 snapshot·renderer 원인 증명으로 세지 않는다. 실제 CORE 본체 여유 계약은 SDK 전방 거리와 별개다.

두 카메라 구간의 관측 경계 방향 42.4°/36.4°에 native yaw 138.375°/144.183°를 더하면 world 180.8°/180.6°다. 해당 경계가 서쪽 직선이고 로봇이 아직 정렬 중이라는 가설을 지지하지만 consumed-frame 인과 증명은 아니다. 현재 drivable_turn_left와 ExpectedPath dropped를 실제 도로 곡률로 동일시하지 않는다. 현재 목표는 centre 대신 영상 border exit를 사용한다. 두 비교 후보는 (A) 현재 연결된 metric centreline의 법선 폭·같은 경로의 목표 선택과 (B) 독립 수용된 관측 경로의 odom 연속성이다. B는 현재 거절·만료·이동 예산을 유지하며 검증되지 않은 turn을 승격하지 않는다. Leg7·8·10 원본과 벽·gap·straddle·crop·회전된 직선/곡선 대조를 같은 가드로 평가한다.

공식 [SLAMTEC C1 사양](https://www.slamtec.com/ko/c1/spec)은 거리오차 ±30mm와 분해능 15mm를 구분한다. 이 값을 Gaussian σ나 모든 조건의 절대 상한으로 환산할 근거는 확인하지 못했다. 소스의 σ=0.02는 초기 upstream import에서 상속됐으며 C1 실측 교정 근거는 미확인이다. 따라서 센서 잡음·빔·안전 margin을 낮추는 변경은 채택하지 않았다. [Jazzy Nav2 RPP](https://docs.nav2.org/jazzy/configuration_and_development/configuration_guide/controller_plugins/configuring_regulated_pp/)는 경로 방향 정렬과 추종을 분리하는 연구 비교 사례다. 이를 현재 CORE의 pivot 승인이나 새 명령 입력으로 대신 사용하지 않는다.

## 2026-10-13 · 실제 몸 경로 재생과 D-737 수정

Leg10 최종 zero 이전 sim54.7 스캔과 이후 CORE HOLD의 sim55.4 스캔은 서로 다르다. 후자의 실제 관측·프로필·신선한 스캔을 정상 원격에서 기존 CORE로 재생하면 의도 `(v,w)=(0.03696873,0.11942469)`의 여유는 25.3mm, 정지 거리 21.4mm다. 기존 선속도만 줄이는 호 집합은 9.4368mm를 선택하여 실제 HOLD와 일치한다. 임계 빔은 591번이며 근접 기억 대신 현재 LiDAR가 선택됐다. 재개 거리 51.4mm보다 작으므로 재개나 미래 충돌 없음의 증거는 아니다. 관측 값과 수신 시각의 일치는 정확한 소비 포인터 증명도 아니다.

[D-737](../adr/D-737-line-body-command-curve.md)은 일반 CAMERA의 검사·발행 곡률과 속도 상한을 맞춘다. 정적 LINE 제한의 정상 원격 RED는 4 NEW이며 공통 제한 함수로 수정한 8e81b91a9의 관련 회귀는 106 PASS·NEW 0이다. 기본 NAVIGATION·MANUAL·DOCKING 제한은 그대로다. 몸 검사와 최종 후보 쪽의 정상 원격 RED는 실제 Leg10 임계 빔, 다른 곡률·같은 곡률의 속도 증가 교체, 검사 후 선·각 cap 증가 및 zero cap의 7 NEW를 확인했다. 기존 실패 목록에 넣지 않았다.

592510e05의 독립 SOURCE 검토는 CORE 명시 연결과 신선한 일반 관측에서만 legacy 추가 호를 생략하고, 같은 snapshot의 clipped pair를 일반 tracking decision에 그대로 반영하도록 확인했다. 최종 공통 감속·zero만 허용하며 다른 후보는 기존 `motion_unconfirmed` HOLD다. 다른 모드의 obstacle_gap, 복구·bridge·junction 쓸기는 기본 legacy 의미를 유지한다. 리뷰에서 발견한 zero/tiny intent의 cruise 부활과 원본 decision pass-through 오인도 커밋 전에 수정했다. 실제 ReturnController의 contained tracking 회귀를 추가했다. 원격 GREEN·구조·설치 검증과 새 전체 Gazebo 실행은 이 SOURCE 승인과 별도다.

목표점 A/B 오프라인 비교는 아직 채택하지 않았다. A는 일부 이전 구간에 페인트 겹침 반례가 남고, B는 실제 48개 관측에서 독립 수용 가능한 경로가 없었다. 안전 빔·잡음·margin·hysteresis를 바꾸거나 현재 거절한 경로를 기억으로 되살리는 수정은 하지 않았다. 원본 지도 완주·새 실행 반복·main 착지·push·실물 수용은 미완료다.

592510e05의 정상 모델 PC 회귀는 몸 검사·실제 lane-return manager·LINE 발행 경계·traffic bridge·차선 추종·LOST 재개·최종 cmd_vel cycle 203 PASS·terminal 0·NEW 0이다. 최종 후보가 다른 곡률이거나 더 빠를 때 거절하고 zero/tiny를 유지하는 회귀를 포함한다. 복구·교차로·다른 모드 및 구조 회귀는 후속 gate이며 새 Gazebo 주행 결과는 아직 없다.

19c66b862의 복구·arc·bridge·junction·권한·횡단보도·swarm·구조·문서 회귀는 685 PASS·NEW 0이다. 그러나 독립 후속 검토에서 일반 추종 이외 후보의 정적 공통 clip 호가 legacy 검사에 포함되지 않는 반례를 찾았다. raw `(0.08,0.8)`와 cap `(0.1,0.01)`의 실제 LINE 호는 `(0.001,0.01)`이며 base point `(0.052,0.078)`에 접촉할 수 있다. 수정한 실제 원격 전진·후진 회귀 e9664ab60은 2 NEW·87 PASS로 재현했다. 첫 점 선택이 접촉하지 않았던 실패 시도도 보존했고 회귀의 실제 전제부터 고쳤다.

a914201e8은 독립 SOURCE 검토 뒤 같은 cap snapshot의 실제 공통 clip 호를 기존 몸 검사에 추가했다. 전진의 LiDAR·기억·초음파 그룹과 후진의 기존 좌표 변환·몸 윤곽에 추가하며 legacy 검사·정지·재개 기준을 제거하지 않는다. CORE-bound generic 호출도 더 보수적으로 거절될 수 있다는 D-737 6항을 기록했다. 일반 추종의 검사 속도 fence와 달리, 다른 manoeuvre의 검사 이후 cap 증가 및 기존 tiny-speed pivot 근사의 전역 해결을 주장하지 않는다. 최종 원격 회귀와 새 전체 Gazebo 실행은 별도 gate다. Leg11은 준비 카드만 만들었으며 예약·빌드·주행하지 않았다.

a914201e8의 최종 정상 모델 PC 회귀는 877 PASS·34 warnings·terminal 0이며 known_failures 판정 NEW 0이다. 전진·후진 정적 공통 호 반례, 기존 충돌·관측·일반 추종·실제 contained return·복구·bridge·arc·junction·권한·횡단보도·swarm과 구조·문서 검사를 포함한다. 경고는 기존 문서/라이브러리 경고이며 이 결과는 source 계약 회귀다. 설치 이미지·Gazebo 완주·실물 수용으로 대신 세지 않는다.

## 2026-10-13 · Leg11 실행과 Fleet 정체 판정

- c66d19b83의 원본 Git blob 전체 7,554파일을 동결하고 새 17패키지를 빌드했다. 설치 2,726파일과 원본 지도·고정 모델 계보를 검증했다. 새 정지 점검은 두 로봇의 명령·이동 0, 실제 SDK/CORE 법칙·640빔·CORE 단독 최종 publisher·native pose와 OFF·lease·pending·프로세스·포트 종료를 확인했다. 빌드 전 자원 거절 한 번은 기록을 보존했고, 정상 SIM 자원이 다시 확보된 후에만 빌드했다.
- 같은 소스의 첫 구간 Leg11은 0.370781538m 이동했으며 지도 도착은 false다. Leg10의 legacy 추가 호로 인한 일반 CAMERA 몸 HOLD는 재현되지 않았다. 최초 native zero는 sim48.569초이며 직전 SDK 전방 거리 0.094548m가 stop 0.10405m보다 작았다. CORE는 TRACKING이고 이후 세 구간에서 양의 명령이 다시 나왔다.
- 최종 zero는 sim56.329초다. 수신 순서는 Fleet `stall` → CORE `junction_stop` HOLD → native zero이며, 직전 SDK는 front 0.133506m·blocked false·can_rotate true다. 최초 SDK 거절과 최종 Fleet 정체 종료를 구분한다. 정책 실패·E-stop은 이번 실행에서 재현되지 않았다.
- Fleet의 현재 정체 판정은 실제 시간 20초 안에 경로 진행 0.05m를 채우는지를 본다. 마지막 약 20 wall초 동안 sim시간은 약 8.738초, 실제 위치의 누적 이동은 약 42.3mm였고 같은 두 native 자세의 원본 경로 투영 변화는 약 48.7mm다. 완전히 정지한 20초로 해석하지 않는다. 내부 progress reset 시각을 직접 기록한 것은 아니므로 정확한 경계 tick을 확정하지 않는다.
- 종료 후 OFF·정지·lease 해제·pending 0·자기 프로세스/포트/lock 종료와 전체 source/install 해시 이상 0을 확인했다. 1,697개 샘플 자세의 차체 paint·wall·외부 겹침은 0이나 연속 접촉 없음과 지도 완주의 증거는 아니다.

다음 비교는 같은 AI PC와 c66d19b83·지도·모델·물리·잡음·안전 기준·Fleet 정체 20 wall초/0.05m·주행 예산을 유지하고, 실행 성능 변수는 CPUQuota만 600%에서 1200%로 늘린다. MemoryMax 6G는 유지한다. 별도의 domain·포트에서 기본 SIM 6코어/8GiB 조건과 추가 여유 12코어 확인, 자기 12/8 lock, 실제 cgroup 제한 readback을 실행 전에 요구한다. RTF·CPU 제한·실제 진행·SDK 거절을 함께 기록한다. 초기 계측 밖 warmup과 후속 관측 구간을 구분하고, RTF가 개선돼도 정체가 남으면 성능만의 설명을 기각한다. 이 비교 준비와 예약은 주행 성공이 아니다. 전체 지도 완주·새 실행 반복·main 착지·push·실물 수용은 미완료다.

## 2026-10-13 · CPU 12 비교 Leg12 종료

- 같은 c66d19b83 전체 동결본으로 새 17패키지를 빌드했다. creator가 직접 반환한 경로·내용·SHA를 검증한 예약 하나만 handoff하고 정상 SIM 자원과 추가 12코어 여유를 다시 확인했다. 실제 정지 점검은 CPU `1200000/100000`·MemoryMax 6GiB, 두 로봇의 명령·이동 0, 이전과 동일한 지도·모델·법칙·640빔·SDK 프로필·CORE 단독 최종 publisher·종료를 확인했다. 주행은 별도 최신 자원·동결 해시 확인 뒤 한 번만 실행했다.
- Leg12는 0.367661837m 이동했으며 도착 false다. 주행 구간 RTF는 Leg11 0.435에서 Leg12 0.857로 개선됐다. 최종 zero 직전 20 wall초의 동일 native 자세 경로 투영 변화는 약 52.8mm다. Leg11 정체에 성능 기여가 없었다고 결론 내리지 않는다. 초기 warmup은 계측 밖이며, 창별 실제 clock/receipt 계산을 전체 실행의 정상 실시간 보장으로 확대하지 않는다.
- 최초 zero sim75.366초 직전 SDK는 front 0.079404m, 마지막 zero sim89.165초 직전은 0.059050m였고 두 경우 blocked true·can_rotate false였다. 해당 zero 근처 CORE는 TRACKING이며 traffic은 APPROACH 감속이다. SDK 거절과 실제 zero의 수신 순서는 확인했지만 정확한 소비 frame·임계 빔의 원인은 아직 재생해야 한다.
- 마지막 zero 약 3.245 wall초 뒤 별도 관측에서 CORE `obstacle_ahead` HOLD, body gap 0.016039m < stop gap 0.0214m가 나왔다. 감독 runner가 OFF·cancel했고 Fleet 최종 상태는 canceled다. 이번 실행은 Fleet stall 재현이 아니다. HOLD의 age null만으로 관측 만료를 단정하지 않으며 일반 scoped 계산인지 legacy 계산인지도 원본 scan 재생으로 대조한다.
- OFF·정지·lease 해제·pending 0·자기 프로세스/포트/lock 종료, source 7,554·install 2,726 해시 이상 0과 진단 오류 0을 확인했다. 두 로봇 각 2,745개 샘플 자세의 차체 겹침은 0이나 연속 접촉·도로 내부 수용은 아니다. CPU 증가만으로 완주 해결은 미수용이다. SDK 임계 거리와 후속 CORE 몸 여유를 따로 재생하며 안전 기준·잡음·빔을 그대로 유지한다.

Leg11 기록의 첫 문서 회귀는 새 로그 제목 형식 오류로 2 NEW였다. 해당 미착지 항목의 제목을 별도 교정 커밋 90f76dbee로 고치고 생성 색인을 갱신했다. 같은 정상 모델 PC 문서 회귀는 terminal 0·NEW 0, harness lint는 error 0이다. 기존 커밋과 실패 원본을 보존했고 제품 로직·Gazebo 동결 소스는 바꾸지 않았다. 지도 완주·독립 반복·main 착지·push·실물 수용은 미완료다.

## 2026-10-13 · Leg13b 자연 HOLD 해제와 SDK 회전 거절

- Linux 시험 PC의 SSH 연결을 재확인했고 접속이 복구됐다. 첫 재사용 점검의 설치 inventory 거절, 순수 감독 selfcheck의 잘못된 기대값, Linux 쉘의 CRLF 거절 원본을 보존했다. 정정한 LF 12개 스크립트의 원격 AST·두 bash-n 검사와 감독 selfcheck는 통과했다. 제품 소스·안전 기준·잡음·빔·시간/거리 한도는 바꾸지 않았다.
- c66d19b83 소스 7,554개와 Leg12 설치를 명시적으로 재사용했다. 설치의 원래 2,726개 해시는 모두 같으며 추가 launch bytecode 6개를 각각 원본 소스·Python header·typed recursive compile 결과로 검증해 2,732개 재사용 manifest를 따로 만들었다. 원래 manifest는 보존했다. 지도 계보에 추가로 기록된 source bytecode 2개도 같은 방식으로 검증했고 기존 지도·모델·법칙·프로필·640빔은 같았다. cache 생성 주체는 미확정이며, 새 빌드나 모든 cache의 일괄 수용을 주장하지 않는다.
- 정상 SIM 6코어/8GiB와 추가 여유 12코어를 확인한 뒤 CPUQuota 1200%·MemoryMax 6GiB에서 정지 점검을 실행했다. 두 로봇 명령·이동 0, CORE 단독 최종 publisher, native LOCALIZED 각 124개와 종료 5조건을 확인했다. 별도 새 creator-owned 예약과 최신 자원·전체 해시 확인 뒤 주행을 한 번 실행했다.
- 감독은 기존 한도 안에서 CORE `HOLD/obstacle_ahead`를 기다리고, 다른 안전 실패는 그대로 종료한다. Leg13b는 0.374786833m 이동 후 Fleet `stopped/stall`로 끝났으며 도착 false다. CORE 장애물 HOLD는 실제 발생했고 약 0.295 wall초 뒤 TRACKING으로 풀렸다. RECOVERING 관측은 없다. Leg12의 감독 즉시 OFF/cancel과 구분한다.
- 최초 zero는 sim77.265초, 최종 zero는 sim84.362초다. 최종 zero 8.55ms 전 SDK는 front 0.127828m > stop 0.10405m·blocked false이지만 can_rotate false였고 CORE는 TRACKING/FREE였다. 이후 SDK blocked가 true가 됐으며 종료까지 false 전환을 관측하지 못했다. CORE HOLD는 최종 zero보다 7.390 wall초 뒤, Fleet stall은 10.466 wall초 뒤다. 따라서 CORE HOLD 해제만으로 native 주행은 재개되지 않았다. 수신 순서에 근거한 원인 분리이며 내부의 정확한 소비 frame 증명은 아니다.
- 실제 spawn heading은 west 역방향 끝 접선이다. 카메라 경계의 세계 방향 약 180도만으로 현재 몸 아래 도로가 직선이거나 로봇이 36도 잘못 정렬됐다고 단정하지 않는다. 원본 graph의 해당 구간 접선은 빠르게 변하며 출구 직선을 앞서 관측했을 가능성을 따로 평가한다. centre와 border 후보의 정지 구간 SOURCE 재생에서는 기록된 SDK GateInputs 분류를 적용한 반사실 계산이 모두 zero를 냈다. 다음 비교는 목표점 조정과 일반 곡선 명령의 실제 sweep 검증을 분리하며, 제자리 회전 검사를 단순히 끄거나 이전 거절 목표를 부활시키지 않는다.
- OFF·정지·lease 해제·pending 0·자기 프로세스/포트/lock 종료, 소스 7,554·재사용 설치 2,732 전체 해시 이상 0과 진단 오류 0을 확인했다. 두 로봇 각 2,787개 native 샘플의 paint/wall/outside/other 겹침은 0이나 연속 접촉 없음·지도 완주·실물 수용을 증명하지 않는다. 지도 완주와 독립 반복은 아직 미완료다.

## 2026-10-13 · 같은 지점 정지의 원인 분리 (run1–run13)

Leg1–13b는 모두 0.29–0.37m에서 멈췄다. 정지 사유를 하나씩 고치는 대신 같은 C66 동결 소스·설치에서 한 번에 한 변수만 바꿔 13회 실행했다. 실행 폴더는 AI PC `~/rosy-test/lap-c1noise-a`, 스크립트 사본은 `X:\DevTemp\lap-c1noise\`다. 지도 완주는 아직 false다.

| 실행 | 바꾼 한 가지 | 이동 | 종료 |
|---|---|---:|---|
| run2 | LiDAR 잡음 σ 0.02→0.0035, 분해능 0.03→0.001 | 0.431m | 교통 정책 감속 뒤 Fleet stall |
| run3 | 교통 정책을 출하값 DISABLED로 | 0.915m | 북서 모서리 `camera_line_not_visible`, 감독이 0.2초 뒤 취소 |
| run5 | 감독이 HOLD를 제품에 맡김 | 1.062m | 후진 복구 1회 뒤 `LOST/reselection_required` |
| run7 | 서쪽 도로 네 모서리를 `bend` 장소로 | 0.172m | `junction_aborted/motion_unconfirmed` |
| run13 | 지시가 걸린 동안 몸 스캔 뷰 급전 | 0.517m | 첫 bend 통과, 벽 쪽 2cm 치우친 뒤 SDK `can_rotate` 거절로 stall |

1. **SIM LiDAR 잡음.** 출하 σ 0.02m는 upstream 기본값이다. 정지한 실물 C1은 0.2m 안 0.6mm, 0.5m 안 최대 3.4mm다([측정](../validation/crosswalk-core-gate-sim-2026-10-10/result.md)). SDK는 640빔의 최근접 점을 쓰므로 벽이 매 스캔 약 3σ 가깝게 읽힌다. 차로 중심과 벽은 116mm, 회전 여유는 92.6mm라 남는 23mm가 사라진다. 앞선 세 SIM은 작업공간 사본만 고쳤다. 수정 `0e81e9de5`. run5에서 `can_rotate` 거절은 1,638회 중 0회였다.
2. **실행기의 교통 정책 ENFORCED.** 출하 SIM 설정은 DISABLED다. 이 지도에는 정지선이 없고 도로 관측기는 흰 벽 밑단을 정지선으로 읽는다(`stop_line_approach` 61회). 벽 오인식 자체는 남아 있다.
3. **감독 스크립트의 즉시 취소.** HOLD 0.6초 뒤 차선이 다시 보였다. 제품의 판정은 CORE 복구와 Fleet 20초 stall이다.
4. **bend 장소 없는 사이트 지도.** `--site-map-import lane_graph.yaml`은 교차점 4개만 만든다. 반경 약 6cm의 90° 모서리는 카메라만으로 돌지 못한다(2026-10-09 [서쪽 모서리 기록](../validation/lane-west-bend-candidate-2026-10-09/result.md)과 같다). 모서리 사이 직선 0.33m는 bend 선행 구간보다 짧아 도로의 모든 모서리가 bend여야 한다.
5. **enforce 기준에서 기동 승인 불가.** CORE의 승인 함수는 `return_body_clear`도 묻는데 그 스캔 뷰는 차선 복귀 중에만 채워졌다(거절 333건 모두 뷰 없음). 수정은 `fix/enforce-junction-scan-view` `62de9e712`. 사이트 기준은 보정된 IR 판정이 필요한데 두 로봇 launch의 SIM IR은 미보정이라 `junction_turn`이 false고 Fleet이 `JUNCTION_TURN_UNSUPPORTED`로 거절한다.

**남은 차단.** enforce에서 SDK는 제자리 회전 원을 이동 곡선에도 적용한다. 벽 옆 차로에서 2cm 치우치면 조향이 모두 0이 되고 스스로 벗어나지 못한다. 이동 곡선의 실제 sweep 검사([설계 초안](2026-10-13-camera-forward-stopping-sweep-design.md)은 `fix/gazebo-map-lap`에 있다) 또는 shadow·사이트 기준과 SIM IR 보정 연결 가운데 어느 기준으로 완주를 수용할지 정해야 한다.

관찰 주의: 실행 중 `gz model -p`를 따로 부르면 자세 스트림이 0.25초 넘게 비어 SIM 자세 어댑터가 `native_gap`으로 영구 철회한다(run1).

## 2026-10-13 · 물리적 한 바퀴와 남은 정지 (run14–run53)

같은 실행기에서 원인을 하나씩 걷어 냈다. 수용 기준은 SDK enforce다. 여섯 브랜치가 로컬 main에 있고 푸시하지 않았다.

| 원인 | 수정 | 브랜치 |
|---|---|---|
| SIM LiDAR 잡음이 실물의 6–30배 | σ 0.0035m, 분해능 0.001m | `fix/sim-lidar-c1-noise` |
| 지시가 걸린 동안 몸 스캔 뷰가 비어 승인 불가 | 교차로 지시나 호가 살아 있으면 뷰 급전 | `fix/enforce-junction-scan-view` |
| Fleet `bend_in_m`이 지연을 보상하지 않아 2cm 늦게 꺾임 | 최고 속도 × (자세 나이 + 전송 여유)만큼 앞당김 | `fix/fleet-bend-in-latency-lead` |
| 테이프 추종기의 가짜 교차로 목격으로 `junction_unexpected` | 지도에 장소가 없으면 짧은 `straight`로 기각(한 주행 3회) | `fix/fleet-dismiss-unmapped-junction` |
| SDK가 제자리 회전 원을 전진 곡선에도 적용 | 후보 곡선의 정지 궤적이 비면 승인(D-740) | `feat/sdk-forward-arc-sweep` |
| 호를 로봇 자세에 붙여 출구에서 5cm 어긋남 | 호의 원을 지도에 고정(D-744), 출구 오차 약 6mm·1° | `feat/map-anchored-lane-arc` |

실행기 쪽에서 맞춘 것도 있다. 서쪽·동쪽 모서리 일곱 곳을 `bend` 장소로 넣었고, 경로 위에 서 있던 rosy_01을 옮겼고, 교정되지 않은 SIM IR에 교정값을 주었다. 원형 교차로의 가상 신호는 접근 방향이 맞지 않아(`approach ""`) 진입을 내주지 않으므로 실행기에서 뺐다. 이것은 제품 결함으로 남아 있다.

**결과.** run45와 run46에서 로봇이 한 바퀴를 돌고 둘째 바퀴에 들어섰다(run46 4.37m, 호 세 개 모두 `map_anchor_used`). Fleet의 `arrived`는 아직 없다. 실행의 절반쯤은 완주하지 못한다.

**남은 정지와 그 원인 (run53–run56).** run37·39·42·44·48·52는 남서 교차로 앞에서 `junction_corner_hold`로 끝났다. 처음 세운 가설(W1 굽이의 코너 프레임이 2초 래치에 남는다)은 run53의 keep_debug 기록으로 버렸다. 기록이 보여 준 것은 다음이다.

- 추종기는 굽이 자신의 바깥선을 교차로 선으로 읽는다. run53에서는 W2 진입 직선에서 `junction_transverse` 0.318m(꼭짓점 0.097m 너머)였고, 통과가 `waiting`으로 끝나 Fleet이 `junction_unexpected`로 주행을 끝냈다. 다음 장소가 0.84m 앞이라 Fleet의 지도 기각(0.9m 안에서는 기각하지 않음)도 걸리지 않았다.
- W1에서는 다음 교차로 SW의 실제 선이 호 가운데에서 0.41–0.43m로 읽혀 넘겨진다. SW 앞에서 추종기는 `corner_left`를 내므로, 이 넘겨받은 목격이 없으면 `junction_corner_hold`가 난다(추정, 직접 재현하지는 않았다).
- 수정: 굽이 자신의 바깥선은 넘기지 않는다(D-507 9항, `fix/bend-own-corner-sighting`, 로컬 main). 오버레이로 넣은 run54는 Fleet 기준 한 바퀴와 둘째 바퀴 일부, run55는 세 바퀴를 돌았다. Fleet이 한 바퀴를 센 것은 run54가 처음이다.
- run55에서는 W3를 47° 돈 뒤에도 바깥선이 `junction_fork` 0.17m로 읽혀 `waiting`이 한 번 났고 Fleet의 기각이 한 번 쓰였다. 모양만으로는 SW의 실제 선과 갈리지 않아, 지도의 다음 선 거리로 가리는 D-754(`feat/bend-next-line-in`, Proposed, 미착지)를 만들었다.
- run56은 둘째 바퀴 W3에서 `motion_unconfirmed`로 끝났다. CORE가 정책 시계를 읽고 0.034초 뒤 올라온 snapshot이 `snapshot_future`로 거절된 한 틱이었다. 수정: 거절되면 시계를 새로 읽어 한 번 더 묻는다(D-740 개정 2, `fix/sdk-snapshot-future-skew`, 로컬 main). SIM 구성에만 닿고 실물은 열려 있다.
- 열린 정지: run54·55는 W2를 나온 뒤 차선이 보이지 않아 W1 굽이의 기준점을 잡지 못하고 `no_anchor`로 끝났다(굽이 간격 0.58m).

**반복 주행.** 양방향 도로와 원형 교차로는 Fleet의 교통 구역이라 주행의 끝이 구역 밖으로 옮겨지고(`stop_moved LAP_END→NE`) 반복은 `TRIP_STOP_IN_ZONE`으로 거절된다. run52는 서쪽 도로를 일방통행으로 바꿔 반복 주행을 받아들이게 했다(계획 4.07m).

**Isaac.** 같은 수정을 합친 소스에서 여덟 번 모두 `camera_lane_lost`였다(0.111m, 0.181m, 0m). Isaac 경로는 프로세스 안의 CORE와 주행 가능 영역 추종기를 쓰고 위 수정이 닿지 않는다.

**열린 제품 결함.** 가상 신호 접근 방향, `line/lane_guide` 생산자 없음, 흰 벽을 정지선으로 읽는 도로 관측기, 칠을 보지 못하는 SIM IR, 양방향 도로에서 끝나거나 반복하는 주행을 막는 구역 규칙.

관찰 주의: 원격 실행기를 기다릴 때 같은 ssh 명령 줄 안에서 `pgrep -f <스크립트>`를 쓰면 자기 자신이 잡혀 끝나지 않는다.

## 2026-10-14 m14–m16 — 서쪽 횡단보도 (D-573 개정 5)

모델 PC, `lap-main-side` 빌드(브랜치 `fix/crosswalk-look-in-corridor-frame`), 진단은 설치본 끝에 붙인 기록기(`artifacts/xwalk-mN.jsonl`, 제품 코드 아님).

- m14(첫 안, 방향만 지금 보이는 차로로): 접근해 살피기는 통과했고, 건너는 중 첫 바퀴에서 `crosswalk_person_present`로 섰다.
- m15(검토 고침 반영): 같은 자리, 건너는 중 정지. 진단: 줄무늬 위에서 카메라 차로가 불확실성 0.046 m, 기울기 0.29로 나왔고, 그 여유가 구역 가장자리에 합쳐져 몸 앞 상자가 양쪽 0.143 m가 되었다. 벽 반환 53개(y≈−0.14)가 상자 안에 들었다. m10–m14의 건너는 중 정지와 같은 원인이다.
- 고침: 건너는 중 몸 앞 상자의 폭은 구역 자신의 차로 가장자리로 재고(여유 없음), 몸이 축에서 비스듬한 만큼만 넓힌다(개정 5 6항).
- m16: 다섯 바퀴 모두 서쪽 횡단보도 앞에서 서고(`looking` 약 5.4 s), 살핌 구역 안 반환 0개로 건넜다. 다섯째 바퀴 뒤 서쪽 도로에서 `lane_lost` → Fleet `stall`로 끝났다(횡단보도와 무관, 차선 놓침 문제).

