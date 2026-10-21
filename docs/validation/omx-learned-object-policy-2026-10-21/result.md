# OMX 실제 RGB 학습·native 물체 정책 평가 — 진행 증거

## 판정과 완료 조건

현재 목표는 **미달성**이다. 실제 시연 25개와 ACT 10,000 step 학습·재적재는
완료했지만, 학습 정책의 새로운 Gazebo 물체 과제 20회 중 최소 18회 성공은
아직 입증되지 않았다. 원격 단위 시험, offline MAE, 관절 goal 성공은 물체 과제
성공 수에 합산하지 않는다. 본 문서는 진행 중인 증거이며 최종 수용 보고서가 아니다.

## 실제 데이터와 선택한 checkpoint

선택한 시연은 batch 7·9·10·11·12·14·15·16에서 각 3개, batch 17에서 1개로
총 25개다. 독립 SIM 정답과 실제 RGB 66,080프레임의 변환·전체 readback을
모델 PC에서 검증했다. 20 train / 5 validation을 분리했고 정규화는 train에서만
계산했다. 최초 학습과 후속 학습 모두 원본 전체 검증부터 수행했다.

| 산출물 | 고정 식별자 |
|---|---|
| 선택 policy revision | `487024ca467ada59c6ac562052f16fcc1848bd70d9f595068793a6e3811de254` |
| Dataset revision | `ccae88060d34dd8b2273f3ae1407524d2b61974474616343f3efc92eacc4cdee` |
| 정규화 SHA256 | `b76fa00fcba81620c252164ecf51fb8b8812bbc9f9aab042a4e8ad3c88cc5b9a` |
| Model weights SHA256 | `b80dc0b03afc8c13036020796b941542d1657a1963e53557962defdd0ce86718` |

모델 PC 실행 `omx-object-training-288fac1ad185df82`는 ACT 10,000 step,
seed 42750, n_action_steps=1을 실제 완료했고 저장 모델 재로딩 예측 일치도
확인했다. main 학습률 0.0001 / backbone 0.00001의 실제 optimizer 그룹을
사용했다. 전체 validation MAE는 0.005564797514183465rad, 상수 예측은
0.29584911500909206rad다. 관절 한계 위반 0, offline 판정은 `offline_only`다.

첫 실행 `omx-object-training-5a2d82ce6eb05697`도 실제 10,000 step과 재적재를
완료했지만 MAE 0.2840533379436038rad로 보존·미선택했다. 두 학습의 curation,
split, 정규화는 동일하며 생성된 dataset revision은 서로 다르다. optimizer
진단은 [별도 보고서](../omx-act-optimizer-2026-10-21/result.md)에 기록했다.

Batch 8은 teacher 3/3 성공 뒤 의존 파일 6개 drift로 전체 제외했고, batch 13은
teacher 2/3 성공 뒤 joint-state stale로 전체 제외했다. 이 두 batch와 선택분의
합계는 **31 시작 / 30 teacher 성공 / 25 학습 편입**이며 생애 전체 실행 수가 아니다.
실패 원문·제외 사유를 보존한다. Teacher 위치·lift 지표는 학습 정책 지표가 아니다.

추가 MODEL-PC 수치 진단 `omx-selected-step-margin-1`은 같은 선택 weights와
원래 validation split의 Episode마다 균등한 64개 frame, 총 320개를 평가했다.
실제 reader state/action을 원본과 대조하고 PNG hash도 검증했다. 모델을 수정하거나
명령을 실행하지 않았다. 원본 PNG와 reader의 손실 인코딩 RGB를 따로 비교했다.

| 수치 진단 | Reader RGB | 원본 PNG |
|---|---:|---:|
| 표본 MAE (rad) | 0.0052625402 | 0.0052403915 |
| 현재 state 그대로 예측한 MAE (rad) | 0.0082721692 | 0.0082721692 |
| 예측 target과 현재 state 차이가 0.04rad 초과 | 56/320 (17.5%) | 59/320 (18.4375%) |
| 최대 관절 차이 (rad) | 0.0466811657 | 0.0466764569 |

이 계산에서 원시연 target도 7/320개가 0.04rad를 넘었다. 이는 표본 frame의 state와
target 비교이며 실제 명령 승인 시점의 판정과 구분한다. 낮은 offline MAE만으로
0.04rad 실행 단계 조건을 만족한다고 주장할 수 없다. 현재 native 실패 원인은
관측/lease 신선도이며, 이 추가 진단만으로 실제 단계 제한 실패를 확정하지 않는다.

진단 결과 SHA256: `2dafffb7427e73112cbae28153a3f10e922fe9b59f37406df156ce26cfceb363`.

## 실제 native 연결 검증과 실패 보존

초기 calibration은 원 관측 500ms 제한 또는 1초 lease 만료로 종료됐다.
정책 원장의 최초 저장을 권한 발급 전에 수행하되 binder의 원본 재검증을 유지해
초기 결속을 약 1.4초에서 약 0.22초로 줄였다. 이후 wall 계측은 세션 잠금 대기
177–263ms, 전체 guarded 추론 경로 안의 numerical 단계 11–14ms를 관측했다.
이는 numerical 단계가 순수 CNN 시간이라는 뜻은 아니다.

Private actor의 명목 watchdog 주기를 20ms에서 100ms로 조정한 c5afc6f9 runtime은
calibration 실제 추론 12회·정책 명령 0회·attempts 0·정리 완료·exit 0으로 통과했다.
최종 확인한 원 입력 나이는 최대 479.089ms였다. 명목 주기는 실제 정지 반응 시간의
상한이 아니다. 일반 runtime 기본값은 그대로다.

첫 고정 campaign `omx-learned-campaign-bdd38d664bc0340d`는 위 checkpoint와
runtime, 성공 기준을 고정했고 **20 시작 / 20 종료 / 20 정리 확인 / 0 물체 성공**으로
종료됐다. 20개 canonical 결과와 수집된 원문이 일치하고 archive·extraction map의
SHA256 40개를 재검증했다. Fetch receipt는 `OBSERVATION_NOT_ATOMIC`이며 파일
시스템의 원자 snapshot이라고 주장하지 않는다.

| 전체 20회 기록 | 확인값 |
|---|---:|
| 물체 과제 성공 | 0/20 (목표 18/20 미달) |
| 반환되어 기록된 candidate | 114 |
| durable command intent | 106 |
| 실제 accepted goal UUID | 100 |
| terminal 상태 4 / code 0인 관절 goal | 95 |
| terminal 상태 5인 관절 goal | 3 |
| cancel ACK 후 terminal 미기록인 관절 goal | 2 |
| 원 joint 관측 신선도 실패 | 17회 |
| 원 camera 관측 신선도 실패 | 2회 |
| lease 만료 실패 | 1회 |

실패 종료 시 독립 관측의 lift·stable 값은 모두 0, XY 오차 229.265131mm,
Z 오차 10.000000mm다. 모두 `incomplete_trial_observation`이며 놓기 후 오차나
해제 후 안정 시간으로 해석하지 않는다. 관절 goal 95회 성공을 물체 성공으로
합산하지 않으며, cancel ACK만 있는 2개를 terminal 완료로 바꾸지 않는다.

완료 원장 SHA256: `2fac17fce6a55b82199a1a4ef5323c3b9f525bc182f17b709198f84be7c6160f`.
고정 campaign SHA256: `fa612239c771a2e9442cd6ec5f689143c291ca879bd98233e8e555e8e9d6b660`.

아래는 첫 4회의 상세 사례이며 전체 20회의 시작·실패 원문을 보존한다.

- Trial 1: 실제 관절 goal 24개 완료 뒤 25번째 goal 수락, 이후 원 관측 신선도
  검사로 취소됐다. 마지막 goal 수락은 원 관측 후 448.757ms, cancel ACK는
  519.135ms, 최종 CANCELED는 548.532ms다.
- Trial 2: 첫 goal 성공 후 두 번째 intent가 저장됐으나 goal UUID·event 없이
  원 관측 신선도 검사에서 거절됐다. 두 번째 candidate 생성 시 원 관측은 이미
  342.609ms였다. Intent만 있다고 실제 goal 전송을 주장하지 않는다.
- Trial 3: lease 만료로 기록된 candidate·정책 goal 0회 종료됐다.
- Trial 4: 원 관측 신선도 검사로 종료됐다. 4회 모두 실행 정리가 확인됐다.

Trial 4 수집 이후 로컬 관리 명령이 Windows 명령 길이 제한으로 실패했다.
원격 프로그램을 SSH stdin으로 보내도록 관리 스크립트를 수정하고, 종료·정리·소스
결속을 확인한 자기 캐시만 정리했다. 데이터·모델·원장·root release는 보존했다.
원 HOLD ledger를 별도 보존하고 같은 campaign의 5회차부터 중복 시작 없이 재개했다.
앞선 별도 b7a36cc348e899b0은 디스크 부족으로 배포 단계에서 실패했고 과제 시작은 0이다.

후속 비교 후보 a2422cff50은 policy actor 자식에만 OMP/OpenBLAS/MKL thread 1을
설정하고 실제 torch thread 수를 기록한다. 기존 cohort에는 적용하지 않는다.
현재 quota 측정은 10초 동안 100 period 중 3회 throttling, 누적 throttled_usec
287256을 보였지만 torch가 단독 원인이라는 증거는 아니다. 효과는 별도 native
calibration과 고정 campaign에서 확인해야 한다.

해당 a2422cff50 calibration은 6개 candidate 기록 후 원 joint 관측 신선도 실패로
종료됐다. 실제 torch thread는 1, interop은 24였고 정책 goal·물체 과제 시작은 0이다.
이어 초기 설치 파일 검사를 관절 intake lock 밖으로 옮긴 4dddf3fc2d는 원격
86 PASS / 1 SKIP / 0 NEW였지만 실제 calibration은 10개 candidate 후 현재 joint
관측 신선도 실패로 종료됐다. 기록된 원 입력 나이는 103.51–270.48ms였으며,
이 수치로 종료 시 현재 관측 신선도까지 통과했다고 주장하지 않는다. 두 실행 모두
정리가 확인됐고 실패 원문은 각 `omx-policy-candidate-smoke-<revision>-<nonce>`에 보존했다.

후속 967dfc3415는 idle calibration을 검증된 설치 metadata의 0.8초 정책 주기에
맞춘다. 다음 capture 전에 대기하고 매 cycle 시작 시각과 최소 간격을 receipt에 기록한다.
기존 빠른 calibration 실패는 추가 부하 시험 결과로 보존한다. watchdog과 lease 갱신은
각 10Hz, 모든 신선도·최종 admission 검사는 유지한다. 실제 loop를 실행하는 회귀
테스트는 이전 코드에서 간격 위반으로 실패했고, 수정 후 원격 관련 검사 52 PASS /
0 NEW를 확인했다. 이 idle calibration 통과만으로 submit·journal·이동 중 관측이나
실제 물체 성공을 주장하지 않으며 별도 engineering 물체 과제로 검증한다.
실제 967dfc3415 calibration은 9개 candidate 후 원 관측 신선도 실패로 종료됐다.
정리 확인은 true, 물체 과제 시작과 정책 goal은 모두 0이다. 마지막 기록의 추론
전체 시간은 464.37ms였고 설치 검사 112.60ms, 초기 lock 대기 146.64ms,
capture 68.21ms, 최종 lock 대기 42.82ms, 최종 검사 78.90ms가 포함됐다.
따라서 운용 주기 일치만으로 해결됐다고 판단하지 않는다.

동일 설치 파일의 합성 Python 경쟁 진단 `omx-hash-contention-1`은 실제 물체
평가와 분리했다. 2회 반복·각 12개 측정에서 1MiB 해시 읽기의 중앙값은
495.60/498.97ms, 8MiB는 99.34/110.35ms였다. 경쟁 thread가 없을 때는
각 약 11/12ms였다. 모든 측정에서 전체 파일 SHA를 확인했다. 이 측정은
실제 ROS 경합의 원인 확정이나 신선도 상한 보장이 아니다.

dc2ae11177은 공통 파일 검증의 읽기 단위만 8MiB로 바꾸며 경로 containment,
전체 SHA·최종 크기 검사를 유지한다. 검증당 일시 block 메모리는 약 2MiB에서
16MiB로 늘 수 있다. 빈 파일·8MiB 경계·그 뒤 17바이트 tail의 끝 변조와 크기
오류를 포함한 원격 관련 검사 72 PASS / 1 SKIP / 0 NEW와 독립 코드 검토를
마쳤다. 선택 checkpoint는 동일하며 별도 native calibration으로 효과를 확인한다.

## 유지한 실행·성공 기준과 시험 범위

원 입력·생성 시각, 500ms 관측·action 신선도, 최대 1초 lease, 0.04rad 단계 제한,
0.8초 goal/최소 제출 간격, 600초 전체 예산을 유지한다. 원 모델 출력을 clip·교체하거나
teacher로 대체하지 않는다. Startup HOME은 별도 프로세스로 종료된 초기화다.
실제 accepted UUID와 terminal 상태 4/code 0이 있어야 관절 goal 성공이다.

물체 성공은 독립 관측으로 lift 30mm 이상, XY 오차 10mm 이하, Z 오차 5mm 이하,
실제 gripper open·해제·분리와 10mm/s 이하 속도 2 SIM초를 모두 요구한다.
SIM DetachableJoint 부착 보조를 사용하며 width/position/geometry 증거로 결속한다.
접촉력 센서·실물 집기·랜덤 초기 상태 일반화·Fleet 운영 승격은 입증하지 않았다.

CPU 비교 후보의 원격 검사 66 PASS / 0 NEW와 읽기 전용 코드 검토를 완료했다.
최초 잘못된 test 경로 요청은 exit 4 / 실행 0으로 보존했고 통과로 계산하지 않는다.
이 시험과 calibration은 실제 20회 물체 과제 성공을 대신하지 않는다.

이전 학습 수정과 보고서는 로컬 main c3ae44ae3f에 정식 병합됐다. 후속 private native
runtime과 본 진행 보고서는 아직 최종 착지 전이다. GitHub push·실물 실행은 하지 않았다.
Road-surface 사람 검수는 사용자 우선순위에 따라 OMX 이후로 보류하며 여전히 0/24다.
