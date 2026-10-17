# OMX 첫 현장 시험 기록지

D-770, 2026-10-18 실물 시험용 미작성 기록지다. 빈칸은 미확인이며 통과가 아니다.
[실행 절차](2026-10-17-omx-next-day-collection.md)의 profile·teacher·acceptance 입력과 연결한다.
현재 실제 시연은0회다. 아래 실물 항목은 오늘 원격 소프트웨어 검사로 채우지 않는다.

## 시작 시 확인

| 항목 | 실제 관측·근거 경로 | 확인자·시각 |
|---|---|---|
| follower 식별과 단독 버스/ROS Action 소유 | 미작성 | 미작성 |
| 현재 자세, 지지하는 하중과 전원 차단 후 지지 수단 | 미작성 | 미작성 |
| 물체·집게 양 끝·인접 구조물·전체 작업 공간 시야 | 미작성 | 미작성 |
| 현장 정지 수단, 독립 watchdog과 powered stop 실측 | 미작성 | 미작성 |
| 기존 native controller PID/start ticks·실행 binary hash | 미작성 | 미작성 |
| watchdog PID/start ticks·해당 검수 원본 | 미작성 | 미작성 |
| topic·publisher GID·유일 Action server와 client 배제 | 미작성 | 미작성 |

기존 bounded commissioning 절차의 수용 자료를 사용한다. collector가 controller나 watchdog을
시작하지 않는다. 영상이 fresh이거나 native cancel이 성공한 사실만으로 물리 정지를 통과시키지 않는다.

## 측정과 설정

| 항목 | 값·단위·측정 방법·근거 |
|---|---|
| workcell_id / instance_id / rig_revision | 미작성 |
| calibration_revision과 ordered6 joint names | 미작성 |
| 여섯 native-radian normalization endpoint 쌍 | 미작성 |
| 각 관절/집게의 허용 위치·속도·가속도·시작 오차 | 미작성 |
| 제한된 과제의 시작 배치·목표·native-rad teacher 단계 | 미작성 |
| top/front 실제 shape·encoding·source clock | 미작성 |
| 실제 영상 간격 분포·누락·시차, fps와 허용 jitter/skew | 미작성 |
| 세션 시간과 저장 공간 하한 | 미작성 |

정규화의 전체 보정 범위와 이번 과제에 허용한 국소 구동 범위는 각각 검증한다.
nominal vendor URDF·예시10Hz·짧은 passive 관측값을 실측 제한으로 간주하지 않는다.
허용치를 임의로 늘리거나 프레임을 복제해 수집을 계속하지 않는다.

검수 뒤에만 private profile/teacher를 고정하고 canonical SHA-256을 acceptance에 묶는다.
acceptance의 여섯 검수 사실·rig/보정 revision·만료 시각을 실제 근거와 함께 확인한다.
설정 변경이나 수용 만료 후에는 다시 확인한다. 카메라 환경 readiness는 이 검수 사실을 발급하지 않는다.

## 첫 수집과 원본 확인

check → preflight → 한 session 한 시도 순서로 실행한다. preflight는 목표를 보내지 않는다.
첫5회 목표에는 중단과 실패도 남긴다. 다음 시작 배치와 정지 상태는 매번 확인한다.

| 시도 | session/cycle·원본 경로 | 종료 이유·HOLD/terminal | 실제 물체 과제 판정·확인자 |
|---|---|---|---|
| 1 | 미작성 | 미작성 | unknown |
| 2 | 미작성 | 미작성 | unknown |
| 3 | 미작성 | 미작성 | unknown |
| 4 | 미작성 | 미작성 | unknown |
| 5 | 미작성 | 미작성 | unknown |

원본 manifest/teacher/profile/acceptance, 요청·native 수용/결과·종료 journal, RGB, 실제 관절과
controller reference, 환경 receipt와 시간 창이 남았는지 확인한다. `complete`는 물체 과제 성공이 아니다.
암실·과노출·시각 만료·source 단절·owner 이상은 중단하고 보존한다. 자동 재개하지 않는다.
정상 실행만 남기려고 실패 원본을 삭제하거나 종료 사실을 바꾸지 않는다.

## 전송·검토·학습 확인

| 항목 | 결과·근거 경로 |
|---|---|
| 첫 실제 Fleet→모델 PC collection 전송과 양쪽 hash receipt | 미작성 |
| 실제 reader inspect, 영상·관절/reference·시각 보존 | 미작성 |
| 실제 영상을 본 사람의 outcome/reviewer/reason | 미작성 |
| 독립 session/cycle의 train/eval/test 배정 | 미작성 |
| ACT 연결 smoke와 별도 process model/pre/post 재적재 | 미작성 |
| 실데이터 학습 run·고정 산출물·독립 평가 | 미작성 |

세 개 독립 세션의 첫 분할과2step 학습은 연결 시험에 해당한다. 데이터 양·과제 성공률·
환경별 성능을 수용하는 근거로 쓰지 않는다. 학습 정책의 물리 실행은 별도 owner/모델 수용과
독립 과제 평가 단계로 진행하며 오늘의 준비나 첫 수집으로 G4를 완료 처리하지 않는다.
