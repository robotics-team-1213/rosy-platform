# 실제 공정 컴파일 연결 점검 — 2026-10-03

D-413의 전체 고정 셀 수용 목표는 유지한다. 이 기록은 호스트의 앱 조합·접수·조작 계획 증거이며 ROS-SIM 완료가 아니다.

- `rosy_gateway.cell_compiler.PalletizingCellCompiler`가 기존 공정의 Recipe/Cell 로더, `compile_job`, `compile_plan_bundle`을 Fleet의 주입 포트에 연결한다. 설치 조합이 공정 artifact digest와 양수 허용 오차를 제공한다. 이 digest의 공급망 검증은 호출자의 책임이며 클래스가 설치 파일을 검증한 것으로 간주하지 않는다.
- 원본 `src/site/cell/examples/omx_sim/{recipe,cell}.yaml`을 그대로 사용한다. 2층, 팔레트별 슬립시트 1장, 팔레트 2개를 18개 transfer와 `(9, A)`, `(18, B)` 완료 표지로 컴파일한다. 작업의 carry height 변조는 재컴파일 비교에서 거부된다.
- 실제 Fleet proposal/resolve API를 통과하고, 서비스 principal의 admission은 거부되며 이름 있는 운영자가 승인한다. 기존 dispatcher, 해석 Skill, Action API, Fleet/OMX SQLite 원장으로 앞의 상자 4개를 처리한다. 다음 단계는 독립 목표 증적을 제출하기 전까지 실행되지 않는다.
- 첫 슬립시트는 `GRASP_DEPTH_BELOW_FINGERTIPS`로 거부된다. 원본 시트 두께 0.002 m가 현재 profile의 fingertip overhang 0.00257 m보다 작다. 로컬 Action은 `PHASE_RUNNER_START_UNKNOWN` HOLD로 남고 시트 phase와 추가 명령이 생성되지 않는다. 모든 자원 점유와 후속 WAITING 단계가 유지된다.
- 이 보호 조건을 제거하면 같은 시험이 HOLD 대신 ACTION_SUCCEEDED로 실패한다. 검증 후 planner 원본을 바이트 단위로 복원했다.
- 실제 네 wheel을 X: 임시 source에서 빌드하고 새 venv에 설치했다. gateway/process/execution의 import가 venv `site-packages`임을 확인했고 저장소 import 경로 없이 18개 transfer와 양쪽 표지를 재검증했다. `pip check`는 0, ROS import는 없었다. CI의 기존 명시적 wheel 설치 목록은 네 패키지를 이미 포함한다.

ROS 목표·그리퍼 읽기와 독립 goal producer는 호스트 시험 포트다. 실제 UDS peer credentials, ROS owner lifecycle, 물체의 이동·그리퍼 접촉과 Gazebo 목표 evaluator는 이 기록으로 증명되지 않는다. 얇은 시트를 현재 도구로 집는 방법과 해당 접촉 증거를 해결한 뒤 원본 18개 transfer 전체의 ROS-SIM 수용을 계속해야 한다. 시트 두께 변경이나 손가락 보호 조건 삭제로 수용을 대신하지 않는다.
