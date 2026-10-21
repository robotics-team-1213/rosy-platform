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
runtime, 성공 기준을 고정했다. 현재 확정 prefix는 **4 시작 / 4 종료 / 0 물체 성공**이다.
계획 분모는 20이며 5회차부터 계속 실행 중이다. 이 cohort는 이미 18/20에 도달할 수 없다.

- Trial 1: 실제 관절 goal 24개 완료 뒤 25번째 goal 수락, 이후 원 관측 신선도
  검사로 취소됐다. 마지막 goal 수락은 원 관측 후 448.757ms, cancel ACK는
  519.135ms, 최종 CANCELED는 548.532ms다.
- Trial 2: 첫 goal 성공 후 두 번째 intent가 저장됐으나 goal UUID·event 없이
  원 관측 신선도 검사에서 거절됐다. 두 번째 candidate 생성 시 원 관측은 이미
  342.609ms였다. Intent만 있다고 실제 goal 전송을 주장하지 않는다.
- Trial 3: lease 만료로 추론·정책 goal 0회 종료됐다.
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
