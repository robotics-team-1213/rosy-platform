## D-756 OMX 모방학습 준비의 미완료 항목과 재개 조건

**Status:** Accepted (2026-10-14)

## Context

사용자는 OMX-L 교시·녹화와 모방학습을 우선하고, Pilot의 OMX-F 수동 조작 및
LeRobot/Hugging Face Hub/Spaces 연동을 함께 요청했다. 실행 PC는 Fleet PC 등을
검토 중이며 HF 계정·조직은 미정이다. 할 수 있는 준비는 수행하고 나머지는 ADR로
남기라는 요청에 따라, 이 결정은 보류 사유와 완료 증거를 고정한다.

2026-10-14 소스 확인: `middleware/devices/omx/profile/config/omx.disabled.yaml`은
`enabled: false`, `hardware_plugin: ""`이고 Pilot 드라이버는 SIM API를 사용한다.
실물 장치의 현재 보유 여부를 추정하지 않는다. 이번 작업에는 실제 연결 대상·실측
프로필·보정 revision이 제공되지 않았다. 기존 D-496의 실물 수용 조건을 유지한다.

## Decision

1. 첫 녹화는 공식 LeRobot 0.4.4 native leader 경로로 준비한다. leader의 body 단위는
   -100..100 정규화, follower는 `use_degrees=false`, gripper는 0..100이다.
   ROSY SIM rad 데이터와 자동 병합하지 않는다. 녹화·업로드는 별도 명시 작업이다.
2. 설치 PC 주소는 코드에 고정하지 않는다. Fleet PC를 선택하더라도 워크셀 실행기·
   venv·데이터 경로·장치 소유를 구분하고 Fleet 서비스와의 자원 경합을 확인한다.
   데이터 기반 학습·평가는 모델 PC 역할이며 원격 CPU 합성 시험은 운영 학습이 아니다.
3. 새 Pilot 실물 API나 드라이버를 임의로 만들거나 disabled profile을 활성화하지 않는다.
   실측 profile과 D-18 API/스키마 계약을 함께 확정한 뒤 D-496 순서로 구현한다.
4. 데이터/모델 Hub 전송 도구는 registry에 둔다. curation은 업로드하지 않는다.
   실제 계정이 정해질 때까지 네트워크 경계는 대역 시험으로 검증하고,
   실계정 왕복 완료로 보고하지 않는다. byte receipt와 reader/model 적재는 별도 증거다.
5. Spaces는 우선 공식 viewer를 검토한다. 공식 README에는 OAuth `read-repos` 설정이
   있지만 이것만으로 우리 private dataset 접근·고정 revision 열람이 검증되지는 않는다.
   필요한 권한·revision 동작을 실제 계정에서 확인한 뒤 배포 여부를 정한다.
   공개 전환으로 접근 문제를 우회하지 않으며 Space에 장치 제어를 넣지 않는다.

## 현재 수행한 검증

- 녹화 설정·native reader·검토/분할·Hub 경계·기존 preflight 등 원격 73개 통과, NEW 0.
- 후속 `8ddaf61a3`: 공식 `lerobot-train`으로 합성 영상 train split을 CPU에서 2 step 학습했다.
  저장된 모델·전처리기·후처리기를 새 CLI 프로세스 종료 후 적재하고 실제 fixture 관측으로
  유한한 6축 출력을 확인했다. train 통계에 eval episode 값이 섞이지 않는지도 검사했다.
- 같은 후속 시험에서 Hub readback 중단 → 손상 응답 거부 → 같은 commit 재시도가
  새 업로드 없이 성공하는 것을 확인했다. 해당 원격 시험 12개 통과, NEW 0.
- 테스트는 `test/test_omx_lerobot_integration.py`와
  `learning/registry/policy/test/test_hub_sync.py`로 재실행할 수 있다.
  장치를 연결하지 않았고 Hub 실제 전송·GPU 학습·실물 성공률은 측정하지 않았다.

## 보류 항목과 재개 조건

| 항목 | 현재 막힌 조건 | 재개 시 입력 | 완료 증거 |
|---|---|---|---|
| 실물 녹화·환경 lock | 워크셀 PC/장치 경로·실측 제한·보정 미지정 | PC, leader/follower ID와 by-id, 카메라, rig/calibration revision, 실측 제한 | 단독 owner·정지 readback, 실제 episode 영상/관절 동기화, 선택 host의 버전 lock과 reader 재독출 |
| Pilot OMX-F 수동 조작 | 실물 API 계약·측정 profile·BENCH 증거 없음 | D-496 측정값, joint/gripper map, recovery/owner 계약 | API Ref+스키마, 별도 driver와 전체 설치 경로, SIM 오접속/leader 소유/timeout/reconnect 거부 시험, BENCH→DEVICE |
| 실데이터 모방학습·평가 | 실제 검토 데이터와 독립 평가 과제 없음 | 검토 dataset revision, train/eval, 과제 성공 조건, 모델 PC 환경 | full train 결과·model/processor hash, 새 프로세스 적재, 독립 평가 보고서; 합성 smoke와 구분 |
| HF 실제 왕복 | 계정·org·private repo·권한 미지정 | dataset/model 대상과 인증, 검토한 파일 목록·공유 범위 | private readback, 업로드 commit SHA, 고정 SHA 다운로드 해시, 실제 reader/model reload |
| Spaces 검토 | 실제 계정의 private 접근·revision 동작 미검증 | 위 dataset SHA와 접근 주체, 필요 시 Space 소유자 | 비인가 접근 거부, 영상/episode 확인, 표시 SHA와 데이터 일치, 재시작 후 같은 SHA, secret 노출 없음 |

장치/설치 담당자는 워크셀·보정 입력을, HF 저장소 관리자는 계정·공유 범위를,
학습 담당자는 데이터 검토와 독립 평가 조건을 제공한다. 담당자의 실명은 아직 지정하지 않았다.
재개 시 위 입력을 private 운영 설정에 기록하고 실행 안내의 검사부터 수행한다.
주소·토큰은 ADR에 기록하지 않는다.

## 기존 결정과 관계

| 결정 | 관계 |
|---|---|
| D-427 | 기존 deploy/learning/middleware 경계를 유지한다. 새 top-level holder 없음 |
| D-429 | source holder와 실행 PC 선택을 구분한다. 폴더 이동 없음 |
| D-430 | owner/stop/recovery 변경 시 독립 안전 리뷰와 수용 증거 필요 |
| D-496 | 실측 profile, 별도 실물 계약, BENCH→DEVICE를 유지한다 |
| D-516 | 모델 PC 학습·AI PC 추론·Fleet admission 역할을 유지한다 |

## Consequences

준비 코드와 합성 시험은 계속 진행할 수 있다. 위 입력이 없는 실물·외부 계정 작업은
보류로 유지한다. Accepted는 이 보류/재개 결정의 채택이며 실물 활성화·학습 품질·
Hub/Spaces 배포 수용이 아니다. 새 API, 런타임 승격, main 착지·push 권한을 부여하지 않는다.

## References

- [실행 안내](../../learning/curation/omx/README.md)
- [구현 계획](../plans/2026-10-14-omx-imitation-preparation.md)
- [D-496](D-496-omx-hardware-arm-control-acceptance.md)
- [공식 viewer README](https://huggingface.co/spaces/lerobot/visualize_dataset/blob/461b74e/README.md) — 2026-10-14 확인; 우리 계정의 접근 시험은 아님.

## 2026-10-14 부록: 시뮬레이션 준비 재개 조건

후속 요청에 따라 [SIM 코드 조사·준비](../plans/2026-10-14-omx-simulation-preparation.md)와
독립 Pilot Compose 입력을 추가한다. D-390의 기존 Gazebo·단일 owner·녹화 경로를
재사용하며 hardware profile, 단위, API와 기존 실물 재개 조건은 바꾸지 않는다.

첫 원격 SSH 실패는 재시도에서 복구되었고 기존 OMX 시험 19개가 통과했다.
그러나 비현장 SIM PC는 예약 반영 가용 메모리가 D-568의 8 GiB 최소보다 작아
새 Gazebo 실행을 보류했다. 자원 여유가 생기면 전용 job을 예약하고 이미지 build,
Pilot 조작·ROS terminal/readback, complete 녹화·lease 중단, LeRobot reader
재독출 순서로 확인한다. 현재 Compose 해석·vendor 패치 적용·OMX-F/L URDF 생성은
실행 준비 증거이며 live SIM 성공이 아니다. 현장 PC나 노트북으로 우회하지 않는다.
Isaac은 USD import부터 별도 확인하며 OMX controller/camera/task와 정책의
closed-loop 과제 성공을 준비 완료로 주장하지 않는다.

후속 준비 commit `91995a99e`의 원격 계약 시험은 129 passed, NEW 0이다.
모델 PC의 Docker 읽기 진단은 소켓 접근 거부로 실패했다. 권한이나 설치를 자동
변경하지 않았으며 비현장 build 환경·사용 가능한 Docker context도 재개 입력에
포함한다. 서비스의 `cpus`/`mem_limit`은 build 제한이 아니므로 이미지 build는
전체 자원을 독점 예약한 비현장 build host에서 별도로 준비한다.

## 2026-10-15 부록: 후속 재확인

미공개 World 안내는 실제 canonical 소비자와 일치하는지 검토했다.
Fleet 패키지의 계정 dependency pin은 사이트·CI와 맞추고, Dashboard에서 Pilot로
돌아오는 기존 계정 SSO 브라우저 시험을 full CI에서 명시적으로 실행하도록 준비했다.
guard 통과는 브라우저 실행·실물 조작이나 학습 수용 증거를 대신하지 않는다.

비현장 SIM PC는 예약 반영 여유가 여전히 SIM 기준 아래였고, 모델 PC의 Docker
daemon 접근 거부와 AI PC 기본 PATH의 Docker CLI 부재도 남아 있었다. 설치·권한을 바꾸거나 현장
PC로 우회하지 않는다. 전용 build 환경, 접근 가능한 Docker context와 이미지,
8 CPU/8 GiB SIM 예약이 준비돼야 실제 조작·녹화·reader 검증을 재개한다.
미정인 HF 계정·조직, 실물 host와 보정 입력은 기존 표를 그대로 따른다.
재확인 범위와 source guard 결과는
[후속 증거](../validation/omx-followup-2026-10-15/result.md)에 기록한다.
