# OMX 실제 물체 집기·놓기 baseline — 2026-10-21

기존 규칙 제어기로 실제 Gazebo 블록을 집고 pallet A의 지정 칸에 놓았다.
독립 관측 판정은 **1회 시도/1회 성공**, 서비스 exit0, 종료 정리 확인이다.
명시적 부착 보조 SIM이며 학습된 정책·접촉/마찰만의 파지·장치 수용 결과가 아니다.

source commit: `27ce202bd1815ee7c82d766a8a772441a2b14f9a`.
run ID: `27ce202bd1815ee7c82d766a8a772441a2b14f9a-72296c50ebc4`.

## 실제 측정

| 항목 | 고정 기준 | 실제 결과 |
|---|---|---|
| 과제 | 20g infeed_block → 기존 compiler의 pallet A 첫 칸 | 물체 중심 목표 (0.2075, 0.0725, 0.025)m |
| 들림 | 초기 관측 높이보다 30mm 이상 | 101.999mm |
| 해제 | 기존 owner의 release receipt·보조 detach echo·실측 OPEN | 모두 확인 |
| 목표 XY 오차 | 10mm 이하 | 0.272711mm |
| 목표 Z 오차 | 5mm 이하 | 약 0.000046mm; 수치 정밀도이며 물리 정확도 주장 아님 |
| 안정 상태 | 선속도 10mm/s 이하·목표/OPEN 유지·진행하는 SIM clock 2초 이상 | 2.246초 |
| 관측 | 별도 읽기 전용 observer, clock/model 식별·유한값 검사 | 1,522개, SIM clock 1.288–77.960초 |
| phase 결과 | 기존 owner/phase journal의 정상 종료 | approach/grasp/transfer/release 모두 SUCCEEDED |
| wall 시간 / 정리 | episode 600초 상한, 자신의 자식 프로세스 정리 확인 | 94.373초 / 확인 |

판정 목표는 정책/teacher 결과가 아닌 고정 source recipe/cell에서 독립 계산했다.
별도 `g2_observer.py`가 Gazebo pose·ROS clock·그리퍼를 읽으며 명령을 발행하지 않는다.
최종 연속 안정 구간에는 0.5초를 초과한 관측 공백을 허용하지 않는다.

## 실행 경계

공식 `tools/remote/remote_omx_native.py`에서 `deploy --host ai --experiment pick-place --sha <source commit>`으로 준비한 뒤
같은 receipt에 `start --approve-isolated-simulation --approve-startup-home`, `status`, `fetch`를 사용했다.
기존 설치된 root 소유 fixed helper가 network-none·PrivateDevices·read-only source/root·4CPU/4GiB를 강제한다.
호스트 정책·helper·공유 SDK를 변경하거나 Docker로 우회하지 않았다.
SDK·source·environment·run script hash 결속과 기존 admission floor를 유지했다.

추가한 `pick-place`는 닫힌 내부 실험 선택자다. 기본 G2 경로는 유지한다.
runtime 결과 폴더만 mutable inventory에 추가하고 source/environment/run script의 변경 검사는 유지했다.
제어기는 기존 `probe_cell_transfer.py`의 단일 ArmCommandOwner다.
SIM grant는 로컬 진단 입력이며 Fleet 승인·full G2·학습 정책의 승인으로 표시하지 않는다.
그리퍼 hold readback 후에만 DetachableJoint를 붙이고 release 전에 분리했다.

## 실패 보존과 회귀

일반 사용자 경로는 실제 video 장치 노출 검사와 UID namespace 제한으로 시작 전에 실패했다.
보호 조건을 유지하고 이미 설치된 지원 native helper로 전환했다.
첫 native 시도는 ROS 도메인 누락, 다음 시도는 부모 준비 검사와 자식 도메인의 불일치로 episode 시작 전에 실패했다.
각 attempts0/정리 확인 결과를 별도로 보존했다. 준비 실패를 물체 성공률의 실제 episode로 섞지 않는다.
첫 native 준비 묶음은 activation 선택자 결함을 시작 전에 발견해 실행하지 않았다.

원격 회귀는 source commit의 세 파일 `test_omx_pick_place_task.py`, `test_native_sim_job.py`,
`test_remote_omx_native.py`에서 **60PASS/0SKIP/NEW0**이다.
RED는 미구현 판정/선택자 10FAIL, activation 선택자·output inventory·부모 도메인 각각 1FAIL로 관측했다.
합성 ACT 연결 6PASS는 이 물체 결과에 합산하지 않는다.

## 원본과 한계

운영자 외부 scratch `pipeline-completion-20261021/omx-object-native-4/`의 deployment/start/status/fetch receipt와 원본을 보존했다.

- terminal fetch archive: 3,060,180 bytes, SHA256 `f30b9288bee59e087839c2ec45fbad9e2db4f35808312a049eb8e26f2a4a521f`.
- `pick-place/result.json` SHA256 `87e545ad87b98ad2edcce3da1617578b05b590d84ec7665101e736c63734f35f`.
- `pick-place/observations.json` SHA256 `560585b4466b0f97741a837543cda56d68f11f7ac2c42ce3814eba96a3611e89`.
- 중간 native 시도와 회귀 로그는 같은 scratch의 `omx-object-native-{1,2,3}`와 `omx-pick-place-*`에 있다.

**전체 학습 파이프라인은 미완료다.** 실제 RGB/관절/명령 시연 수집·분리, 모델 PC 학습·checkpoint 재적재,
같은 checkpoint의 독립 물체 평가 20회와 18회 이상 성공이 남아 있다.
1회 규칙 제어기 성공을 학습 정책 성공률이나 일반화·실물 수용으로 올리지 않는다.
