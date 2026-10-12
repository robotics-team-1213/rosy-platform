# description logs

추가만 한다. 형식: [module harness 설계](../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-15 이전 이력은 `git log -- src/description`를 본다.

## 2026-09-15 · uncommitted · docs(harness): start the description harness record
- 변경: `progress.md`, `logs.md` 추가
- 증거: `python3 -m pytest test/test_robot_runtime.py::test_runtime_builds_distinct_targets_from_shared_dockerfile -q` 1 passed; LOCAL은 미실행 — `src/description`에 `test/` 디렉터리가 없어 host-runnable 대상이 없음 (2026-09-15 Windows)
- gate 변화: 없음(신규 기록). SOURCE GO, LOCAL HOLD, ROS-SIM N/A, ARTIFACT/DEVICE HOLD(io 이미지에 포함, Device 계획과 동일 blocker), FIELD N/A
- 결정: D-61 Proposed
- 교훈: 없음

## 2026-09-16 · uncommitted · docs(harness): hold unrendered description in ROS-SIM
- 변경: 리뷰 반영. ROS-SIM을 HOLD로, `last_verified.commit`을 `uncommitted`로(SOURCE 시험이 미커밋 WIP가 있는 `deploy/robot/Dockerfile`을 읽음)
- 증거: `python -m pytest test/test_robot_runtime.py::test_runtime_builds_distinct_targets_from_shared_dockerfile -q` 1 passed (2026-09-16 재실행). ROS 렌더 자체는 미실행
- gate 변화: ROS-SIM N/A→HOLD (URDF는 robot_state_publisher·Gazebo가 소비하므로 적용 대상이지만 미검증)
- 결정: 없음
- 교훈: 없음

## 2026-09-16 · uncommitted · docs(harness): stop counting the meshes dockerignore check as source evidence
- 변경: 2차 리뷰 반영. SOURCE를 HOLD로(인용 시험은 `.dockerignore` meshes 제외만 확인하고 URDF·io-build 포함을 단언하지 않음), FIELD를 PARKED로(io 이미지에 실리는 패키지)
- 증거: 미실행 — 기록 정정만. 인용 시험 내용은 `test/test_robot_runtime.py`에서 직접 확인
- gate 변화: SOURCE GO→HOLD, FIELD N/A→PARKED
- 결정: 없음
- 교훈: 없음

## 2026-09-21 · uncommitted · fix(sim): use stable primitive drive collisions

- 변경: 시뮬레이션 바퀴 충돌체를 축 방향 cylinder로 바꾸고 종방향 마찰과 횡방향 scrub을 분리했다. DART가 지원하지 못한 mesh collision은 sim 렌더에서 primitive로 유지하고, 물리 모델의 상세 mesh는 그대로 보존했다. SLAM용 odom은 Gazebo model pose, wheel odom은 진단 토픽으로 분리했다.
- 증거: ROS Jazzy 컨테이너에서 xacro 렌더 및 관련 description/gz_sim 시험 통과. `final_22` 실제 주행 52/52, sampled collision overlap `false`, 최소 본체 여유 `0.021789 m`.
- gate 변화: ROS-SIM HOLD→GO(단일 로봇 exact-map collision/odom 범위). ARTIFACT/DEVICE/FIELD는 변동 없음.
- 결정: 시뮬레이션 정답 odom과 바퀴 적분 odom을 한 토픽에 경쟁시키지 않는다.
- 교훈: 구형 mesh collision과 과도한 등방 마찰은 로드 성공 여부뿐 아니라 좁은 공간 회전과 SLAM 궤적까지 왜곡한다.

## 2026-09-22 · uncommitted · chore: update ARTIFACT blocker to Native Image Builder (D-164)

- 변경: deploy/robot/Dockerfile 의존성을 Native Pi Image Builder로 일괄 변경
- 증거: D-161, D-164
- gate 변화: 없음


# description logs

추가만 한다. 형식: [module harness 설계](../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-15 이전 이력은 `git log -- src/description`를 본다.
## 2026-09-29 · uncommitted · feat(sim): select Isaac xacro backend

- 변경: 공통 `robot.urdf.xacro`에 기본 `gz` backend를 유지하면서 Isaac 렌더에서 Gazebo 플러그인만 제외하는 인자를 추가했다.
- 증거: 호스트 Isaac 준비 계약 pytest 통과. Jazzy xacro 렌더는 이 Windows 세션에서 미실행이다.
- gate 변화: 기존 Gazebo ROS-SIM 판정은 과거 증거로 유지한다. 새 Isaac 렌더는 ROS-SIM HOLD다.

## 2026-09-30 · uncommitted · feat(sim): camera_hfov and cam_mount_z xacro args (D-353 5)

- 변경: `robot.urdf.xacro`/`rosy.urdf.xacro`/`rosy_gz.urdf.xacro`에 `camera_hfov`(기본 1.1519), `cam_mount_z`(기본 0.0495) 인자를 추가하고 `upload_robot.launch.py`로 전달했다. 기본값은 이전 URDF와 같다. 실제 Pinky 카메라 프로필 시뮬(`gz_sim/launch/map_v2_fleet_real.launch.py`)이 쓴다.
- 증거: `test_map_v2_fleet_launch.py`의 URDF 체인 계산이 기본값에서 (0.028481, 0.060194) 그대로, 8°·0.05307에서 (0.03317, 0.06700). `python -m pytest src/sim -q` 통과(Windows).
- gate 변화: 없음. 장치 URDF 기하는 기본값이라 바뀌지 않는다.

## 2026-09-30 · uncommitted · docs(adr): pilot ADR 번호를 main 과 겹치지 않게 다시 매김
- 변경: main 이 D-346~D-353 을 다른 결정으로 먼저 썼다. 이 모듈 기록의 옛 번호는 다음으로 읽는다 — D-346→D-362(운전자 실시간 영상), D-347→D-342(수동 한도 계단), D-348→D-343(방·운전석), D-349→D-344(보조 자율), D-350→D-363(카메라 비율·설치 앱), D-353→D-364(차로 유지 인식·재생 벤치). 위 기록은 덧붙이기 전용이라 고치지 않는다.
- 증거: `docs/adr/` 파일 이름·ADR Log 행·코드 주석·시험이 새 번호를 쓴다. D-342~D-344 는 main 의 harness 가 이 pilot 초안용으로 예약해 둔 번호다.
- gate 변화: 없음(번호만).

## 2026-09-30 · uncommitted · docs(adr): 운전자 실시간 영상 ADR 을 D-362 에서 D-368 로
- 변경: 다른 세션이 main 작업 트리에서 D-362(코드 유형별 파일 크기 예산)를 쓰고 있어, 이 모듈 기록의 D-362(운전자 실시간 영상, 옛 D-346)는 D-368 로 읽는다. 위 기록은 덧붙이기 전용이라 고치지 않는다.
- 증거: `docs/adr/D-368-pilot-live-driver-video.md`, ADR Log 행·코드·시험이 새 번호를 쓴다.
- gate 변화: 없음(번호만).

## 2026-10-01 · edca9b2e · feat(description): Gazebo DiffDrive 바퀴 간격 0.0961 → 0.0971 (D-397)
- 변경: `rosy_gz.urdf.xacro` `wheel_separation`을 URDF 접지 간격 2 × (0.04055 + 0.008)로. URDF 자체는 바꾸지 않았다; `tools/calibration/urdf_nominal.py`가 이 URDF에서 `geometry.yaml`을 만든다.
- 증거: `test_urdf_nominal.py`(재생성 비교·드리프트).
- gate 변화: ROS-SIM HOLD(랩 재실행).
- 결정: D-397 Proposed.

## 2026-10-06 · uncommitted · feat(sim): Gazebo IR 바닥 광선, LiDAR 한 바퀴 각도

- 변경: `rosy_gz.urdf.xacro`에 URDF IR 링크 셋의 아래 방향 한 줄 `gpu_lidar`(`ir/left|mid|right`)를 더했다. Gazebo LiDAR `max_angle`을 `π − 2π/640`으로 바꿔 시작 빔이 겹치지 않게 했다(D-468 `return_scan_view`가 겹친 스캔을 거부했다). 장치 URDF는 그대로다.
- 증거: `gz_sim test/test_sim_sensors.py`, 모델 PC xacro 전개와 스캔 증분 0.0098175 확인.
- gate 변화: 없음.

## 2026-10-11 · 7b0a8d965 · refactor: Pinky description 장치 holder 이전

- 변경: D-626 devices/pinky/description으로 이동하며 URDF/mesh/launch/CMake/package bytes를 유지했다. 소비자와 설치 소스 경로를 정렬했다.
- 증거: Pinky 원격 885 성공·2 skip 중 URDF surface/collision geometry 계약 포함, 독립 source 리뷰. logs는 R100 보존 뒤 추가, known_failures 0 NEW/0 known.
- gate 변화: 없음. 새 ROS 렌더/Gazebo/ARM64/실물 geometry 수용은 미확인.

## 2026-10-12 · 508334331 · fix(sim): LiDAR cubemap 경계 빔을 반 간격 이동

- 변경: Gazebo LiDAR의 두 각도 끝점만 반빔 이동해 cubemap face 경계를 피한다. 640개·2pi/640 간격·비중복 한 바퀴·10Hz·잡음 0.02·TF·range·topic은 유지한다. 장치 LiDAR 설정과 vendor 파일은 바꾸지 않는다.
- 증거: 동일 원본 지도와 정지 자세의 두 설정에서 각 102개 동일 header, 전체 거리/강도 GZ↔ROS 일치와 종료·해시 보존을 확인했다. 전체 visual ray 잔차 표준편차는 51.15→20.23mm지만 원본 회전 거절 SOURCE 재생은 7→11/102회 남았다. 모델 PC TDD RED는 기존 grid의 float32 UV=1 실패 1 NEW를 확인했으며 기존 실패로 등록하지 않았다.
- gate 변화: 새 후보의 원격 회귀·독립 리뷰·새 전체 빌드 주행 전 SOURCE/ROS-SIM HOLD. 센서 경계 수정만으로 주행 정지·지도 완주·실물 수용이 해결됐다고 주장하지 않는다.

## 2026-10-13 · c0bb0393c · verify(sim): 빔 위상 SOURCE 회귀 종료

- 변경: 새 위상 SOURCE를 실제 원격 회귀와 독립 리뷰로 GO로 기록하고, 이전 LOCAL 렌더 수용과 새 설치 검증을 분리했다.
- 증거: 정상 AI 원격에서 Gazebo/description/scan/return/Isaac URDF와 문서 경계 시험 610 PASS·7 SKIP·14 subtests·NEW 0. 독립 SOURCE 승인, 실제 source 전체 7,553개 동결·새 17개 패키지 빌드 13.1초를 확인했다.
- gate 변화: SOURCE HOLD→GO. 새 설치 전체 해시·실제 센서 정지 점검 전 LOCAL/ROS-SIM HOLD. 빌드 뒤 연결 실패로 정지 점검·주행은 미실행이며 이전 설치/렌더 수용을 대신 쓰지 않는다.

## 2026-10-13 · c0bb0393c · verify(sim): 새 설치 정지 점검과 원본 맵 Leg9 종료

- 변경: 정상 연결 복구 후 실제 새 설치의 LOCAL 점검과 원본 맵 주행 결과를 기록했다. 새 센서 경계 수정과 주행 정책 실패를 구분했다.
- 증거: source 7553·install 2726 파일 전체 해시 일치, 17개 새 패키지와 실제 640빔 halfphase·SDK 적용 프로필·CORE 최대 전진 0.1 m/s·native pose 계보·정지 명령을 확인했다. Leg9는 0.286048511 m 뒤 control:policy_failed E-stop으로 종료했다. 최초 zero 직전 compiled limits의 can_rotate는 true였다. trip 종료·lease 종료·OFF·정지·프로세스 종료와 해시 보존을 확인했다.
- gate 변화: LOCAL HOLD→GO(새 설치 렌더·센서·정지 상태 점검 범위), ROS-SIM HOLD 유지(지도 미완주). ARTIFACT/DEVICE/FIELD 변동 없음.
- 결정: E-stop을 해제하거나 추가 주행하지 않는다. SDK None과 evaluator 예외를 기존 정지 이후 알림 경로에서 구분한 뒤 원인을 재현한다.
- 교훈: probe의 신선한 limits만으로 SDK 내부 관측 window의 유효성을 증명할 수 없다. 종료된 runner의 exit 0은 지도 도착을 의미하지 않는다.

## 2026-10-13 · 314e06aca · verify(sim): Leg10 본체 여유 정지

- 변경: 같은 원본 지도·반빔 위상·안전 조건의 새 전체 설치와 정지 점검을 거쳐 한 회차를 실행하고 결과를 분리해 기록했다.
- 증거: 17패키지·source 7553/install 2726 해시 일치, 실제 양 CORE 단독 publisher·0 명령·이동 0·640빔·SDK/조향 법칙을 확인했다. Leg10은 0.366485589m 뒤 obstacle_ahead HOLD이며 body gap 0.0094368m < stop gap 0.0214m다. 47.766초의 일시 zero 후 양의 명령이 재개됐고 최종 zero는 54.768초다. 정책 예외·E-stop 0건, 종료5조건·lease 해제·잔존 프로세스 0·포트 닫힘·전체 해시 보존을 확인했다.
- gate 변화: LOCAL GO, ROS-SIM HOLD 유지(지도 미완주). ARTIFACT/DEVICE/FIELD 변동 없음.
- 결정: 실제 경로와 임계 visual ray를 독립 분석하며 이전 Leg9 예외는 미재현 상태로 남긴다. 추가 주행·E-stop 해제·안전 완화는 하지 않았다.
- 교훈: 안전 정지의 반복 원인은 고정 빔 경계 오류와 별개로 검증해야 한다. sampled overlap 0을 미래 궤적·지도 완주 수용으로 대신하지 않는다.
