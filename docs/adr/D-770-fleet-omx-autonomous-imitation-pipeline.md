## D-770 Fleet PC OMX 자동 시연 수집과 모방학습 파이프라인의 완료 기준

**Status:** Proposed

## Context

2026-10-16 사용자 지시: Fleet PC에서 실제 구동하며 학습할 준비를 조사하고 ADR로 기록한다.
Pinky도 준비하되 OMX를 먼저 한다. 사람이 리더를 움직이는 방식만 준비하는 것이 아니라,
에이전트가 실제 OMX를 조작해 데이터를 수집하는 자동화를 포함한다.

D-756의 native leader recorder·검토·분할·공식 ACT 준비를 재사용한다. 다만 그 경로는
`source_mode=leader_native`이므로 자동 교사 데이터를 같은 출처로 표시하면 안 된다.
기존 딸기 과제는 흰 원형 용기에서 꺼내 임시 위치에 놓고 원래 용기로 돌려놓기다.
첫 자동 수집은 이 과제를 작은 단방향 구간으로 나누고 전체 왕복을 parent cycle로 묶는다.

### 이번에 직접 확인한 사실

공유 main `436d52a55`에서 분기한 `feat/fleet-il-readiness`의 소스와 현장 읽기 진단 기준이다.
과거 기록과 오늘의 관측을 구분하며 주소·장치 serial·보정 원문은 공개하지 않는다.

| 항목 | 관측 | 판단 |
|---|---|---|
| 원격 접속 | 일반 SSH는 host key 검증 실패; 기존 Tailscale 인증 SSH로 접속 성공 | 호스트 검증을 끄지 않고 진단 가능 |
| 호스트 | Linux 7.0.0-38-generic, Python 3.12.15 recorder venv | ROS 지원 배포판·실물 controller 호환성은 별도 |
| 자원 | 루트 볼륨 약 111 GiB 여유, 가용 메모리 약 10.7 GiB | 관측 순간의 값이며 작업 예약·장기 수집 용량 보장은 아님 |
| 장치 | OpenRB serial 두 개, USB 카메라 세 종류 | 연결이 실물 구동 수용을 뜻하지 않음 |
| 기존 식별 | 현장 SETUP에 10-12 unplug 식별·모터 ID·보정·수동 teleop 이력 | 현재 기구 한계·작업공간·정지 수용의 대체 증거가 아님 |
| recorder 환경 | LeRobot 0.4.4, torch 2.10.0+cpu, torchvision 0.25.0+cpu, av 15.1.0; pip check 성공 | 준비 문서 CPU 시험 버전과 다르므로 이 호스트 reader/저장 재검증 필요 |
| 보정 | 기존 leader/follower JSON 존재; SETUP에 wrist roll offset와 재보정 주의 기록 | 자동 재보정·설정 초기화를 실행하지 않음 |
| 점유 | 확인 순간 serial fuser 점유 없음; front/top 카메라는 기존 user service가 점유 | recorder의 중복 카메라 open과 임의 서비스 중지 방지 필요 |
| 장애 이력 | 기존 teleop 로그에 USB 소실로 종료 | 짧은 구간·단절 종료·재연결 후 자동 재개 금지 검증 필요 |
| 실물 제어 | 소스 hardware profile 비활성; 기존 G3–G6에는 측정/stop/owner 결선 공백 | LeRobot connect/send_action을 우회 실행해 자동 수집하지 않음 |
| 데이터 | 조사한 기존 LeRobot·IL 작업·cache·Desktop/data 후보에서 native meta/info.json 미발견 | 전체 디스크에 데이터가 없다는 주장은 아님; 새 실제 데이터 확보는 미완료 |

## Decision

### 1. 목표와 완료 범위

목표는 **실물 관측 → 제한된 자동 교사 실행 → 실제 명령/피드백/영상 기록 → 독립 결과 판정 →
검토·독립 분할 → 모델 PC ACT 학습 → 새 프로세스 모델/processor 재적재 → 별도 실물 평가**다.
자동 수집은 첫 실제 데이터셋 확보까지 포함한다. 합성 fixture 학습이나 정지 영상으로 완료하지 않는다.

초기 목표 수량은 프로젝트 제안값이며 품질을 보장하는 표준이 아니다.

| 단계 | 통과 조건 | 산출물 |
|---|---|---|
| G0 현장 준비 | host 환경 lock, rig/보정, 실제 제한, 단독 owner, 정지·단절·재시작 확인 | private 실행 설정, BENCH 증거, readiness 결과 |
| G1 첫 수집 | 짧은 실제 과제 시도 5회; 성공/실패/미판정/개입을 모두 보존 | 실제 RGB·관절·명령·feedback·시간축·outcome, reader 보고서 |
| G2 첫 학습 데이터 | 우선 성공 train 50 / validation 10 / final test 10 cycle 목표; 실제 확보 수량 별도 보고 | 원본 hash, 검토 revision, cycle/세션별 split manifest |
| G3 학습 연결 | train-only 통계, 고정 seed/config, 학습 종료·저장, 새 프로세스 processor 포함 재적재, held-out replay | 학습 로그, model/processor hash, 오프라인 평가 |
| G4 실물 비교 | teacher와 learner를 각각 독립 10회 이상 평가; 우선 learner 성공 8/10을 목표로 검토 | 성공 분자/분모, 실패·개입·정지·시간, 기준선 비교 |

G4 표본은 첫 판단용이며 일반화·무인 장시간 운용 수용이 아니다. learner 성능 부족은 수집 완료와
구분해 원인을 기록하고 G1–G3를 반복한다. 목표 수량을 채우려 성공을 임의 라벨링하지 않는다.

### 2. 자동 교사와 학습 정책을 구분한다

첫 교사는 검증된 local owner에 제한된 목표를 제출하는 결정적 작업 단계로 구성한다.
관측 확인 → 접근 → 파지 → 들어올림 → 임시 놓기 → 독립 outcome 확인 순서다.
복귀·reset도 별도 제한 동작이며 무조건 실행하지 않는다. 다음 목표는 이전 종단과 실제 상태 확인 뒤에만 제출한다.
영상의 픽셀을 보정 없이 관절/공간 목표로 바꾸거나 SIM IK·jaw 값을 실물 값으로 쓰지 않는다.

에이전트의 텍스트 응답·SSH 연결은 실시간 안전 제어기가 아니다. 장치 근처의 bounded executor가
수치 제한·freshness·단독 소유·timeout·stop을 집행한다. 명령 성공 응답은 과제 성공이 아니다.
현재 local owner 실물 결선·독립 stop의 공백부터 닫는다. 무작위 탐색이나 무인 RL로 준비를 대체하지 않는다.

수집 출처는 최소 `leader_native`, `scripted_teacher`, `learned_policy`, `simulation`을 구분한다.
이는 후속 데이터 계약의 요구이며 아직 구현된 public schema라고 주장하지 않는다.
기존 native_review가 모든 입력에 leader_native를 붙이는 경로에 자동 교사 데이터를 그대로 넣지 않는다.
관측, 요청 action, 실제 전달 action, 다음 관측, terminal, 독립 outcome, intervention을 보존한다.
action label의 단위·시각·관절 순서와 정책 실행 의미가 동일해야 한다.

### 3. 호스트·카메라·저장 경계를 고정한다

Fleet PC는 현장 실행·수집과 Fleet를 맡고, 학습·독립 평가는 모델 PC에서 한다(D-516).
현재 현장 CPU venv에 GPU 학습을 얹지 않는다. 작업 예약과 Fleet 지연을 측정하고,
수집 중 디스크 부족·누락·과부하가 발생하면 해당 episode를 불완전으로 종료한다.

기존 카메라 서비스는 먼저 유지한다. 기존 stream을 recorder가 소비할 수 있는지 확인하고,
불가능하면 해당 카메라에 대해서만 명시적 소유권 인계·종료 후 복구를 구현한다.
장치를 동시에 열어 운 좋게 영상이 나오는 상태를 수용하지 않는다.
기존 preview는 약 10 Hz이고 수신 시각을 사용하므로 설정 예시 30 FPS·노출 동기화로 간주하지 않는다.
실제 수집 주기·영상 freshness·누락률·관절/명령 시차를 측정한 뒤 허용 기준을 확정한다.

원본은 새 세션 경로에 저장하고 hash를 고정한다. 원본·검토·분할·학습 출력은 분리한다.
모델 PC 복사 후 byte hash와 실제 reader를 모두 확인한다. 중단 재시도는 원본 덮어쓰기나 자동 삭제가 아니다.
HF 계정·Hub·Spaces는 로컬 파이프라인의 선행 조건에서 제외하고 별도 승인된 전송 단계로 둔다.

### 4. 검토·분할·평가

초기 자동 수집은 실행을 자동화하되 결과 판정기는 독립 관측으로 검증한다.
초기에는 사람 검토를 유지하고, 자동 판정과 사람 판정의 대조 증거가 쌓인 범위만 자동 채택한다.
teacher 성공 주장·모델 동의·관절 목표 도달만으로 물체 이동 성공을 확정하지 않는다.
불확실·시야 가림·물체 낙하·개입은 따로 보존하고 성공 BC 입력에서 제외한다.

왕복의 각 구간·재시도·증강 프레임은 parent cycle 및 수집 세션에 묶어 한 split에만 둔다.
현재 native splitter의 train/eval 두 분할만으로 세 분할·세션 독립성이 구현됐다고 보지 않는다.
최종 test는 튜닝과 반복 채택에 사용하지 않으며, 과제·배치·조명·rig revision별 분포를 기록한다.
파지 대상·용기·임시 위치를 검증한 뒤에만 제한된 배치 변화를 추가한다.

### 5. 실행 순서와 우선순위

1. 오늘 환경·제어·데이터 공백을 evidence로 남기고 기존 G1–G6 및 학습 계획과 연결한다.
2. 실물 owner·제한·독립 stop·카메라 소비 경로를 완성하고 BENCH를 확인한다.
3. 제한 자동 교사와 episode recorder를 연결해 첫 5회 실제 시도를 수집한다.
4. 실패와 provenance를 보존하며 검토·독립 분할·전송·ACT·재적재를 연결한다.
5. 독립 실물 평가 후 필요한 데이터만 추가 수집한다. Pinky는 OMX 첫 수집 뒤 진행한다.

## Alternatives

| 접근 | 판단 |
|---|---|
| 사람 leader 시연만 완료 | 기존 도구 재사용에 유리하나 사용자 요청의 직접 조작 자동 수집을 충족하지 못함 |
| native send_action을 원격에서 바로 반복 | 현재 connect가 configure/보정을 호출할 수 있고 독립 stop/실측 workspace가 닫히지 않아 첫 실행 경로로 선택하지 않음 |
| 검증된 local owner + 제한 교사 + 독립 기록/판정 | 권장. 기존 제어 경계를 유지하면서 실제 데이터와 학습 계보를 연결 |
| SIM/합성 데이터로 파이프라인 완료 선언 | 형식·코드 연결 시험에만 사용. 실물 데이터 완료 증거로 불인정 |

## 기존 결정과 관계

| 결정 | 관계 |
|---|---|
| D-427 | middleware 실행·operations 업무·learning 학습/검토 holder 유지; 새 최상위 폴더 없음 |
| D-429 | source 위치와 Fleet/모델 PC 역할 구분, 폴더 이동 없음 |
| D-430 | owner/stop/구동 변경에는 독립 safety review와 실제 수용 필요 |
| D-496 | 실측 profile·BENCH→DEVICE 유지; 과거 하드웨어 없음 기록은 오늘 연결 관측과 구분 |
| D-516 | 현장 실행과 모델 PC 학습 분리 유지 |
| D-756 | native leader 준비를 재사용하되 scripted teacher 출처와 실제 실행 공백 추가 |

## Consequences

계획 문서의 존재가 아닌 첫 실제 episode와 재현 가능한 학습 산출물이 완료 기준이 된다.
현재는 현장 읽기 진단까지 확보했으며 자동 동작·시연 수집·실데이터 학습은 미완료다.
제어·stop·공간 보정이 미확인인 상황에서는 구현 가능한 비구동 준비를 먼저 진행한다.
본 ADR은 main 착지·push·Hub 공개·정책 운영 승격을 뜻하지 않는다.

### 이번 회차 실행 증거와 재개점

- 기존 front/top producer를 유지한 채 각각 640×480의 advancing frame 3개 이상을 수신했다.
  마지막 프레임의 host-receive stamp 기준 age는 각각 약 64/30 ms였다.
  이미지 노출 시각·camera-to-arm 보정·동기식 IL episode의 검증은 아니다.
- 현장 SETUP·설치 소스 확인 결과 native `connect()`는 `configure()`를 호출하며
  Operating Mode와 PID gain을 쓴다. 단순 연결 검사로 취급하지 않는다.
- 후속 현장 진단은 Tailscale 추가 check 인증을 요구해 중단됐다. 현재 개발 PC의 profile은
  private 설정의 기대 profile과 달랐다. profile 자동 전환·SSH 검증 해제는 하지 않았다.
- 원격 문서 계약 시험을 요청했으나 실행 결과를 확보하지 못했다. 통과로 보고하지 않는다.
  `git diff --check`와 harness lint는 성공했다(0 errors, 기존 검증 시점 경고 30개).
- 다음 입력은 인증된 원격 접근, 실제 제한·독립 stop 수용 증거와 hardware owner 결선이다.
  현재 자동 교사 실행·첫 실제 IL 데이터셋·실데이터 학습은 모두 미완료다.

### 2026-10-16 후속: 접속 복구와 데이터·학습 연결 구현

사용자의 문제 해결 지시에 따라 인증 요청만 반복하지 않고 기존 접속 경로를 대조했다.
현재 개발 PC→AI PC는 정상이며 AI PC→현장/모델 PC의 기존 인증도 정상이다.
개발 PC의 해당 두 호스트에만 SSH ProxyJump를 설정해 일반 SSH/SCP와 원격 시험을 복구했다.
StrictHostKeyChecking을 유지하고 기존 키를 사용했다. 계정·호스트·라우팅 설정은 private에 둔다.
현재 접속을 옛 Tailscale profile이나 인증 URL 대기로 계속 차단하지 않는다.

현장 follower 6개 모터를 읽기 전용으로 재확인했다. 모두 torque 0·hardware error 0이다.
실제 손목 homing offset은 1024이고 기존 `pinky_follower` 파일은 957이었다.
현장에 이미 실제 값과 일치하는 `omx_follower_arm` 파일이 있으므로 재보정/EEPROM 쓰기를 하지 않았다.
카메라 두 개에서 새 640×480 프레임을 수신했으나 현재 영상은 매우 어둡다.
auto exposure 상태를 읽었고 현장 조명 확인을 요청했다. 이 영상으로 물체/경로가 보인다고 간주하지 않는다.

구현된 오프라인 경로:

- 출처를 생략하면 `unverified_native`로 남기고 학습 분할을 거절한다.
- 자동 교사는 고정 teacher SHA, 단위·rig/보정·원본 파일 hash·session/cycle을 manifest에 선언한다.
  실제 파일·episode와 대조하며, 출처 선언 자체를 물리 실행 수용으로 간주하지 않는다.
- 검토한 성공만 포함하고 session/cycle·중복 내용이 train/eval/test를 넘나들지 않게 한다.
- 분할 중 원본 변경을 거절하고 분할 출력 hash를 receipt에 고정한다.
- `native_cycle.py`가 출처·검토·출력 bytes를 재검사한 뒤 공식 ACT CLI를 실행한다.
  별도 프로세스의 model/pre/postprocessor 재적재와 eval MAE·train 평균 기준선을 기록한다.
  final test는 학습/튜닝 지표에서 제외하고 실물 성공률은 null로 유지한다.

이 경로의 실제 LeRobot CPU 합성 fixture 통합 시험이 통과했다. 원격 접속 복구 뒤
문서·기존 native 검토 119개, 신규 출처/분할/학습 연결 관련 45개도 통과했다.
독립 코드 검토의 출처 재검사·분할 중 원본 변경 지적은 실패 테스트로 재현하고 수정했다.
이는 실제 소프트웨어 실행 증거이며 첫 실물 교사 시연·실물 데이터 학습·과제 성공 증거는 아니다.
모델 PC에는 기존 GPU 환경과 분리한 전용 CPU 환경을 설치했다. Python 3.12.3,
LeRobot 0.4.4, torch 2.10.0+cpu, torchvision 0.25.0+cpu, av 15.1.0과
export requirements의 직접 의존성을 고정하고 전체 freeze·pip check를 보존했다.
초기 ensurepip 부재는 기존 uv로 해당 venv 안에만 pip를 설치해 해결했다. 시스템 패키지는 바꾸지 않았다.

소스 `319bbcd38`의 모델 PC 통합 시험은 1 passed다. 실제 LeRobot으로 합성 RGB/관절
3 episode를 저장·재독출하고 train/eval/test를 생성했다. 공식 ACT 2 step 실행,
새 프로세스 model/pre/postprocessor 재적재와 eval 4 frame의 유한한 6축 출력·MAE,
독립 test 분리·train-only 통계·전후 hash를 검증했다. 코드의 순수 검사 45개도 통과했다.
로그는 개발 PC의 private 임시 세션에, fixture 원본/분할/학습/receipt는 모델 PC의
`~/rosy-test/omx-il-env/smoke-20261016-055551/`에 보존했다. 실제 과제 데이터나 GPU 학습은 아니다.

조명 재확인에서 top/front의 평균 밝기는 각각 약 7.87/2.49(0..255),
픽셀 RGB 평균 10 미만 비율은 약 90.9%/98.8%였다. 정상 수신과 관측 가능성은 구분한다.
첫 실물 수집은 여전히 미완료이며, 밝은 작업대에서 실물 owner·실측 제한·정지 조건을
확인한 뒤 제한 교사 동작과 실제 명령/관측을 수집하는 것이 다음 단계다.
현재 source의 readiness를 기본 native 환경에서 다시 실행했다. Lyrical/Jazzy 불일치,
필수 패키지 일부 미발견, trajectory Action 없음과 synthetic joint-state publisher를 확인했다.
이는 기본 graph의 관측이며 기존 private build/overlay 전체가 없다는 주장은 아니다.
원문 `result.json`은 현장 `~/rosy-test/omx-il-readiness-current/`에 보존했다.

최종 회귀: `f48a7a3b8`의 OMX curation/training 전체, 녹화 설정, harness 및 문서 배치
검사는 원격 260 passed / 6 skipped, known_failures NEW 0이다.
모델 PC에 보존된 cycle receipt도 별도 읽기로 확인했다: 모델 파일 7개 hash,
세 분할, 새 프로세스 재적재, eval 4 frame과 `physical_task_success=null`이다.
현장에는 같은 source snapshot을 checksum 확인 후 staging했다. 모델 PC 추가 source staging은
SSH banner timeout으로 완료하지 못했다. 중간에 중계 AI PC가 오프라인이 된 뒤 복구됐으며,
최종 회귀는 복구 후 새 실행으로 완료했다. 네트워크가 영구 안정화됐다고 주장하지 않는다.

후속 재개에서 모델 PC source staging도 완료했다. source `b7cf77838`의 필요한 파일을
전송 hash와 기존 파일 bytes 대조 후 새 snapshot에 배치했고, 전용 venv의
`run-native-cycle.sh --help`를 실행했다. 기존 GPU 환경·장치 service는 바꾸지 않았다.
재확인한 현장 보정/위치 폴더에는 프레임 metadata가 있으며, 이것을 camera-to-arm
보정이나 실물 workspace·stop 수용 결과로 사용하지 않는다. 현재 source/관측 범위에서
그 수용 결과를 찾지 못했고, 실물 owner unit은 여전히 camera preview와 구분해야 한다.
top/front의 어두운 픽셀 비율은 후속 관측에도 약 84.7%/98.4%였다.
첫 실제 자동 시연은 0회로 유지한다. 조명·물리 보정·정지 수용의 미확인값을 추정해
채우거나, 정지 관측을 성공 시연으로 라벨링해 학습하지 않는다.

## References

- [기존 실물 제어 실행 계획](../plans/2026-10-15-omx-hardware-control.md)
- [기존 실제 피드백 증거](../validation/omx-physical-feedback-2026-10-15/result.md)
- [기존 학습 운영 계획](../plans/2026-10-15-omx-learning-operations.md)
- [native 데이터 검토·학습 안내](../../learning/curation/omx/README.md)

## 2026-10-16 후속: 실측 관측 수집과 웹 확인

조명 문제는 이후 밝은 영상으로 해소했다. 기존 두 camera producer를 구독하고,
읽기 전용 실제 모터 관측기를 함께 실행해 MCAP 기록을 종료·재독출했다.
14.432초 동안 각 카메라 145 frame, 실제 joint-state 145개, 총 435개 메시지다.
영상에 앞선 joint-state와의 시차는 top 최대 7.383ms, front 최대 7.369ms였다.
이는 호스트 수신/관측 시각의 대응이며 센서 노출 동기화 검증은 아니다.
모든 모터 torque/error는 0이고 기록 전후 설정은 같았다.

원본 8파일 260,605,655 bytes를 모델 PC에 복사하고 크기·SHA256을 대조했다.
모델 PC의 실제 Jazzy rosbag2 reader로 435개를 다시 읽은 뒤 hash를 재검사했다.
명령은 0개이므로 `imitation_eligible=false`, 실물 과제 성공은 null이다.
실제 자동 시연 수는 여전히 0이다. 원본과 수신 receipt 위치·해시는
[관측 검증 기록](../validation/omx-observation-web-2026-10-16.md)에 남긴다.

사용자의 카메라 직접 확인·필요한 웹 구현 요청에 따라 adapter에 localhost 전용
읽기 전용 commissioning viewer를 추가했다. Fleet 서버는 ROS를 import하지 않는다.
기존 카메라 구독만 사용하고 실제 관측 topic을 기본 synthetic `/joint_states`와 구분한다.
공유 Fleet API나 장치 control 권한을 추가하지 않는다. SSH 인증 경로로만 원격 연결한다.
정지 영상·미래 시각·반복 시각·다운로드 정체 시 오래된 자료를 live로 유지하지 않는다.
영상과 관절 표시의 성공은 실물 구동/stop/보정 수용을 뜻하지 않는다.

## 2026-10-16 후속: 수집 시작의 자동 torque 부작용 확인

현장 설치본 `OmxFollower.connect(calibrate=False)`도 configure를 호출하고,
그 torque_disabled context는 finally에서 torque를 켠다. 그러므로 보정 flag만으로
읽기 전용 연결을 만들 수 없다. 해당 source와 실제 startup register를 별도 보존했다.
기존 read 응답에 goal/profile/current/watchdog 해석을 추가했고 관련 원격 25시험을 통과했다.

실제 두 snapshot에서 여섯 motor torque/error 0, goal=present, 전후 설정 동일이다.
그러나 모든 profile velocity/acceleration과 watchdog은 0이고 gripper current는1750이다.
이는 좁은 동작 범위·독립 stop과 승인된 초기화 경로의 수용을 뜻하지 않는다.
XL430 미지원 current 값은 0으로 오해하지 않고 null로 기록한다.
[실제 source·register·제조사 문서 대조](../validation/omx-native-startup-2026-10-16.md).
실제 자동 시연은 여전히 0회이고 설정 쓰기·torque 활성화는 실행하지 않았다.

## 2026-10-16 병합과 다음 초기화 단계

기존 준비 변경을 로컬 main `585885428`에 병합했다. 영향 범위 1509 passed/14 skipped,
구조·문서 247 passed, 브라우저 3 passed, NEW 0이다. 원래 branch의 개별 커밋은 보존했다.

후속에서는 기존 고정 ROS driver도 GPIO 초기화 쓰기와 기본 torque 활성화를 수행함을
확인했다. 실제 vendor xacro를 확장하고 파일 생성기로 명시적인 register 초기화 59개를
제거하고 자동 torque 선택을 끈 후보를 생성했다. 원본 불변·6 motor flag·hash를 대조했다.
파일 생성기 원격 8시험 통과·독립 검토 완료다. 이 후보는 실행용 수용 profile이 아니며,
driver activation write/service authority·실측 제한·독립 stop·owner binding은 미완료다.
[후속 구현·실행 증거](../validation/omx-preserved-description-2026-10-16.md).

## 2026-10-16 후속: driver lifecycle 결과와 owner 우회 경로 수정

고정 vendor의 start가 초기 command write 실패와 torque enable retry 소진을 무시하고,
stop도 disable 실패를 무시해 SUCCESS를 반환함을 실제 메서드 실행으로 재현했다.
실패를 ERROR로 전파하고 부분 활성화 후 두 그룹 정리를 시도하도록 수정했다.
cleanup 실패를 포함한 10개 compiled-method 시나리오가 모두 통과했다.

D-336의 단일 owner 경계를 위해 vendor direct register/reboot/torque 서비스 등록을
제거했다. read 서비스와 기존 controller/lifecycle 경로는 유지한다. 현재 ROSY source에
세 direct 서비스 caller는 발견되지 않았다. source lock과 Fleet/Pilot 공유 API는 유지하고
두 vendor patch를 compile 전에 적용한다. 원격 관련 pytest22 통과·독립 재검토 완료다.

새 private prefix에서 전체 native plugin build/install·ldd·library load를 확인했다.
실물 controller·ROS node는 시작하지 않았다. 실물 정지·owner HOLD·부하/보정 수용과
자동 시연은 미완료다. [원인·수정·실행 증거](../validation/omx-driver-lifecycle-2026-10-16.md).

## 2026-10-16 후속: native ROS 초기화 실패 경로

외부 consumer 연결에서 누락된 CMake export dependency 두 개를 발견하고 vendor patch로
수정했다. 실제 Fleet ROS 환경에서 전체 plugin 재빌드 뒤 잘못된 고정 포트의 on_init이
ERROR를 반환하고 정상 소멸함을 확인했다. 실물 포트·configure/activate/goal은 사용하지
않았다. 현재 cell owner는 SIM metadata와 gripper 관측에 고정돼 있어 실물 조립과
실제 feedback·HOLD 연결은 별도 수용이 필요하다. 실물 시연 0회와 미완료 조건을 유지한다.
[재현 source와 실행 증거](../validation/omx-native-init-negative-2026-10-16/result.md).

## 2026-10-16 후속: feedback 원본 시각과 HOLD

실물 feedback 연결 준비 중 기존 ROS intake가 같은 원본 message를 매번 새로운 상태로
취급하는 것을 실제 Jazzy 회귀로 재현했다. 원본 시각 진행·age·배열 검사를 넣고 전송
지연을 owner freshness에 반영했다. 거절 message는 watchdog을 갱신하지 않으며 활성
명령은 기존 stale HOLD/cancel로 들어간다. native ROS 8시험과 순수 intake 10시험을
원격으로 실행했다. publisher 물리 출처·독립 정지·실측 수용과 실제 시연은 미완료다.
[원인과 검증 경계](../validation/omx-feedback-source-age-2026-10-16.md).
