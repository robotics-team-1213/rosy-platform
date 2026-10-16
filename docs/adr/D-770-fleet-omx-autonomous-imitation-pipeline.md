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

## 2026-10-16 후속: 작은 이동으로 실측 범위를 식별

사용자 요청대로, 완성된 실측 profile이 이미 있어야만 측정을 시작하는 순환을 피한다.
현재 자세 주변에서 한 관절씩 작은 이동을 수행하고 원본 encoder·두 카메라·명령/종단을
같이 기록해 국소 반응을 측정하는 방식을 준비한다. 작은 명령을 보냈다는 사실만으로
작은 실제 움직임을 가정하지 않는다. 초기 목표/현재 위치·mode·offset 보존과 유한한
속도/가속/전류 또는 PWM 제한의 실제 적용, 정지 경로 확인이 첫 이동보다 앞선다.

측정은 hard stop까지 관절을 밀어 최대 범위를 찾는 절차가 아니다. 확인된 현재 자세
주변만 대상으로 하고, 매 step의 실제 도달·정지·영상 유효성을 확인한 뒤 다음 step을
결정한다. 미확인 종단·관측 지연·오차 증가·통신/모터 오류에서는 자동 재시도/재개하지
않는다. 확인한 작은 범위를 전체 workspace·부하·그리퍼 jaw 수용으로 확대하지 않는다.

제조사 XL330/XL430 문서에서 velocity-based profile의 0은 무제한을 뜻하고, bus
watchdog은 모든 instruction packet의 통신 간격을 감시함을 확인했다. 읽기 통신이
계속되는 owner 고장을 watchdog이 검출한다고 가정하지 않는다.
[XL330](https://emanual.robotis.com/docs/en/dxl/x/xl330-m288/),
[XL430](https://emanual.robotis.com/docs/en/dxl/x/xl430-w250/).

토크 off native 초기화/read를 위한 source 검토에서 InitDxlComm 오류 분기의 자동
Reboot 호출과 read 오류 동안 기존 state 유지 경로를 발견했다. 실물 실행 전에 자동
복구 쓰기·오래된 feedback의 보고 의미를 확인한다. 이 source 발견을 실물 실행 또는
정지 성공으로 기록하지 않는다. 실물 시연은 여전히 0회다.

source-age 수정 뒤 정책 fixture의 생성자 생략을 보완하고 host22·실제 ROS policy4와
runtime8 시험을 통과했다. [후속 검증](../validation/omx-feedback-policy-intake-2026-10-16.md).
## 2026-10-16 후속: 실제 native 초기화·토크 off read

InitDxlComm의 숨은 자동 Reboot를 제거하고 오류 반환은 유지했다. 고정 실제 메서드의
두 fault 분기 재현 뒤 5시나리오가 통과했다. SDK open 직후 device identity·독점 소유를
검사하는 임시 helper를 추가했고 실제 Linux PTY/loader 교착 회귀 6시험을 통과했다.

실제 Fleet에서 constructor 교착과 XML parser dependency 누락을 각각 해결했다.
두 실패의 native serial 송신은 0이며 모든 원본을 보존했다. 세 번째 실행은 실제
on_init·read3회·정상 소멸 exit0이다. 전후 torque/error0·설정 동일이며 송신93개 중
indirect mapping SRAM write72개가 있다. goal/torque/reboot는 관측되지 않았다.
분석기의 SUCCESS 숫자 가정 오류는 설치 enum97u와 원본 로그를 대조해 별도 receipt로
해결했고 장치를 재실행하지 않았다. 실제 원본 시각 진행과 encoder nominal 변환을 확인했다.

이 결과는 물리 보정·독립 stop·구동 또는 시연 수용이 아니다. 첫 작은 이동을 위해
유한 제한 적용·초기 목표 보존·normal write 오류 전파·실물 owner/HOLD와 정지 경로를
계속 연결한다. 실제 자동 시연은 0회다.
[실행·실패·분석의 분리 증거](../validation/omx-native-passive-read-2026-10-16/result.md).

## 2026-10-16 후속: 정상 write 실패와 framework 오류 정지

정상 write가 buffered/multiwrite 실패를 버리고 HW_ERROR에도 목표를 송신하는 것을
고정 실제 메서드 실행의 5실패로 재현했다. 실패를 즉시 ERROR로 전파하고 정상 상태가
아니면 추가 쓰기를 거절한다. write6·오류 callback8시나리오와 원격 관련24시험이 통과했다.

설치 ros2_control은 write ERROR에서 on_deactivate가 아니라 on_error를 직접 호출한다.
vendor의 기본 on_error/on_shutdown은 stop 없이 SUCCESS였다. 두 callback을 stop에
연결하고 on_error는 cleanup 후에도 ERROR로 fault를 FINALIZED에 남긴다. 실제 native
객체의 통신 객체 부재 실패 전파, 전체 plugin 빌드, 실제 HardwareComponent consumer의
12경우 및 상속 기본 callback의 negative control을 확인했다. bus 경계는 double이며
실물 정지·부하·구동을 실행한 것은 아니다. 운영 prefix/service는 유지했다.

유한 제한·초기 목표 보존·실제 상태 출처·owner/HOLD·정지 관측을 이어서 연결한다.
실제 시연은 계속 0회다.
[원인·caller 경로·수정·실행 범위](../validation/omx-cyclic-write-fault-2026-10-16/result.md).


## 2026-10-16 후속: 실제 torque/error 출처와 작은 측정의 전제

사용자의 현재 위치 주변 작은 단계 측정 요청에 따라 전체 범위 선행 측정 없이 좁은
범위를 확인하는 결정을 유지한다. 실제 feedback의 출처부터 연결했다. SDK enable ACK
유실 뒤 cache OFF로 cleanup을 생략하는 결함과 native torque/error 기본값 게시를
고정 실제 메서드로 재현했다. 불확실한 토크 쓰기를 ACK까지 추적하고 실제 cyclic
Torque Enable/Hardware Error Status를 요구·검증·게시한다. 기존 description은 새
candidate로 migrate해야 하며 누락 설정은 실제 bus open 전에 거절한다.

원격39시험 NEW0, 8-patch native 빌드와 old/new 실제 on_init PTY 비교를 통과했다.
실제 torque-off read3회는 fresh 실제 torque0/error0을 확인했으나 ID14 목표 레지스터
1틱 변화로 전후 보존 검사는 실패했다. 송신105개에 goal/torque/reboot는 없었다.
원인은 미확정이며 원본 실패·별도 저장 자료 분석을 남기고 장치를 재실행하지 않았다.
기존 passive read의 native 기본값 검사를 실제 register 검증으로 확대하지 않는다.

작은 움직임은 유한 제한·초기 목표·owner/HOLD·정지 관측 연결 뒤 진행한다. 실제
자동 시연은 0회이며 IL 데이터 수집·실데이터 학습 완료로 기록하지 않는다.
[원인과 검증 범위](../validation/omx-measured-status-2026-10-16/result.md).


## 2026-10-16 후속: native 부재의 목표 레지스터 관찰

보존 검사 실패를 재실행하지 않고 별도 PING/READ-only 관찰30회를 수행했다.
native driver 없이도 ID14의 목표와 현재 위치가 함께3195↔3196으로 바뀌는 전이가
11회였다. 여섯 모터 torque0/error0과 mode는 유지됐다. firmware 원인·이전 mapping
영향을 확정하거나 기존 gate를 통과로 바꾸지 않는다. 첫 활성화의 현재 위치·목표
보존/readback 설계에 이 실제 변화 특성을 반영한다. 실제 시연은0회다.
[독립 관찰과 해석 한계](../validation/omx-goal-readonly-2026-10-16.md).


## 2026-10-16 후속: 측정 시작용 유한 제한의 실제 적용

전체 작업 범위 검수를 먼저 요구하지 않고, 사용자 요청의 작은 단계 측정에 필요한
제한을 토크 OFF 상태에서 먼저 적용했다. 임의의 넓은 workspace나 하중 수용값은
만들지 않는다. 설정 절차와 운영 명령 owner를 구분하고 기존 owner를 우회하는
trajectory 실행기를 만들지 않는다.

commissioning_limits는 알려진 여섯 모터·mode·torque/error0과 독점 소유를 확인한 뒤
명시적인 유한 상한만 낮춘다. 각 쓰기의 원본·의도를 durable 기록하고 정확히 한 번
송신한다. ACK와 전체 모터 readback 뒤에만 다음 쓰기를 허용한다. 오류·불일치·기록
실패·deadline 초과는 중단하며 자동 재시도/복원/resume은 없다. 실제 송신 경계에서도
허용 주소·ID·폭·값·deadline을 검사한다.

원격65시험 NEW0과 독립 검토 후 실제 Fleet에서 cap21쓰기를 완료했다. 여섯 PWM
raw20·profile velocity/acceleration각1, XL330 current raw50을 실제 readback했다.
모든 torque/error0이며 goal/torque/mode/offset/reboot 쓰기는 없었다. EEPROM 상한은
낮은 값으로 유지하고 원본을 보존했다. RAM profile은 재시작 뒤 다시 읽어야 한다.
이는 측정 시작용 설계값이며 물리 안전·부하 유지·작업 범위의 실측값이 아니다.

초기 목표의 현재 위치 동기화와 실제 owner/HOLD/정지 관측을 계속 연결한다.
실제 자동 시연과 IL eligible 데이터는 아직0회다.
[설정·RED/GREEN·실제 송신과 readback](../validation/omx-bounded-commissioning-2026-10-16/result.md).


## 2026-10-16 후속: 토크 OFF 시작 목표의 실제 송신

실제 native driver에서 모든 Torque Enable/Reboot 선택을0으로 고정하고 fresh torque0/
error0 read 뒤 on_activate/start를 한 번 호출했다. enable list는 비어 있고 현재 위치
동기화 목표만 송신했다. 전후 fresh 상태3회와 raw snapshot은 torque/error0·기존 cap을
유지했다. 실제 초기 목표6개의 nominal raw 위치와의 최대 차이는1틱이다.

송신107개 중 목표 SyncWrite는 주소224/폭4의 IDs11..16 한 묶음이다. torque/reboot/
mode/offset 쓰기는 없다. 목표 차이는 송신 후 검증이며 사전 transport guard가 아니다.
SyncWrite 성공은 모터 ACK·물리 도달·독립 stop·실물 owner 수용을 뜻하지 않는다.
운영 controller·trajectory는 기동하지 않았다. 실제 움직임과 시연은 계속0회다.
[실제 시작 목표와 검증의 한계](../validation/omx-bounded-commissioning-2026-10-16/result.md).


## 2026-10-16 후속: 실제 controller·owner 피드백과 stale HOLD

기존 patched native driver와 실제 controller manager·상태 발행기·6관절 trajectory
controller를 별도 domain/namespace에서 연결했다. 모든 Torque Enable/Reboot 선택은
0이며 unconfigured 시작·loaded library·독점 by-id·기존 유한 cap을 확인했다.
현재 committed adapter/core_common source를 그대로 사용했고 stub 피드백은 없다.

실제 관절 상태10개를 owner가 받았으며 JSB를 중단한 뒤 joint_state_stale로 명령을
거절하고 HOLD로 전환했다. Action 전송을 막는 최종 차단 장치까지의 dispatch 시도는
0이었다. 실제 native torque/error 상태46개는 여섯 OFF/error0이고 source stamp가
진행했다. 송신196개 중 cyclic 현재 위치 유지 SyncWrite47회는 별도 집계했다.
Action goal0과 native register 목표 쓰기를 혼동하지 않는다.

설치 ROS parser의 YAML alias 거절과 controller별 params_file 전달 누락을 실제로
해결했다. 앞선 실패와 process137을 보존했다. 성공 실행은 실제 CM exit_group0,
강제 종료 없음·전후 cap/mode/torque/error0 동일이다. 저장 trace 분석의 중첩 char FD
표기 문제는 분석기만 고쳐 해결했고 장치를 재실행하지 않았다.

최신 OFF/error-free 상태가 없거나 fault/deadline이 있으면 controller 활성화·다음
service를 진행하지 않는다. 자식에 독립40초 TTL을 두고 소유 process group을 정리한다.
이 결과는 토크 OFF feedback 결선과 stale admission 거절이며, 실제 accepted goal/
취소·powered stop·독립 물리 정지·운영 owner 재시작 수용을 뜻하지 않는다.
실제 시연과 IL eligible 데이터는 계속0회다.
[실제 경로·실패·판정 범위](../validation/omx-native-controller-feedback-2026-10-16/result.md).


## 2026-10-16 후속: 실제 stationary Action 수용과 cancel terminal

실제 owner와 JTC에 최신 native 관측 위치만 목표로 한 명령1건을 보냈다. 모든
Torque Enable/Reboot 선택은0이며 여섯 실제 torque/error0과 기존 cap을 유지했다.
실제 GOAL_ACCEPTED→CANCEL_ACK(true)→TERMINAL_RESULT(CANCELED5)를 durable
JSONL로 기록했다. owner는 HOLD를 유지하고 재요청을 hold_latched로 거절했다.
두 controller와 hardware를 비활성화한 뒤 CM은 정상 exit0이었다.

저장 trace172packet 중 cyclic 목표35회는 pre 위치와 최대1틱 차이다. torque/reboot/
mode/offset 쓰기는 없으며 실제 OFF/error0 상태34개를 확인했다. 목표 차이는 사후
검사이며 transport guard는 아니다. saved-only 분석의 CRLF 오류는 원본을 남기고
LF 분석기만 추가해 해결했다. 장치를 재실행하지 않았다.

cancel ACK·CANCELED와 토크 OFF 비활성화는 powered 물리 정지의 증거가 아니다.
구동 정지·독립 stop·실측 이동·운영 owner 재시작은 계속 검증해야 한다. 실제 시연과
IL eligible 데이터는0회이며 첫 실데이터 확보 목표를 유지한다.
[실행·실제 이벤트·송신·해석 한계](../validation/omx-native-action-cancel-2026-10-16/result.md).


## 2026-10-16 후속: stop-only 보조 경로와 native 종료 후 독립 인계

명령 owner의 HOLD/cancel과 별도로 commissioning_stop을 추가했다. 확인된 by-id의
독점 소유·실제 device identity 아래 명시한 ID에 Torque Enable=0만 한 번씩 전송한다.
개별 실패 뒤 나머지 OFF를 시도하되 재시도하지 않는다. ACK·실제 readback·cleanup·
기록 성공을 구분하며, 디스크 오류로 OFF 시도를 생략하지 않는다. 운영 profile을
활성화하거나 goal/ON/config 쓰기를 제공하지 않는다. 원격 RED→GREEN92시험 NEW0이다.

실제 모든 native torque 선택0에서 unit main을 SIGKILL로 종료하고 systemd의
control-group 정리 뒤 별도 ExecStopPost가 장치를 인계받게 했다. 실제 ID16 OFF1건의
ACK와 여섯 OFF/error0·기존 cap 보존을 확인했다. stop helper trace13packet의 CRC와
완전 송신을 검증했고 ON/goal/mode/offset/reboot/EEPROM 쓰기는 없었다. 기존 unit을
잘못 cleanup할 수 있는 private supervisor 문제는 fake systemctl로 RED→GREEN 후
실물 실행했다. 원본·수정본·실제 unit 속성과 강제 종료 결과를 보존했다.

이 결과는 토크 OFF 상태의 독립 process-death 인계다. 실제 ON→OFF 물리 정지·처짐·
하중·국소 이동 범위·운영 owner 재시작을 수용한 것은 아니다. 다음 작은 단계의 구동
검증에 이 경로를 연결하며 실제 시연·IL eligible 데이터는 계속0회다.
[구현·시험·실제 인계·판정 범위](../validation/omx-independent-stop-2026-10-16/result.md).


## 2026-10-16 후속: 독립 watchdog과 powered 시험 전 시야 확인

private powered prototype의 first-ON age 검사는 이후 감독 호출이 지연될 때 ON 기간을
보장하지 못했다. 실행 전에 발견했고 해당 prototype은 실행하지 않았다. 별도 all-OFF
fixture에서 실제 Type=notify/300ms manager watchdog과 barrier를 구성했다. 외부
supervisor가 unit/PID/cgroup/InvocationID와 속성을 대조해 admission한 뒤, native가
알림/barrier 성공 뒤에만 hardware를 활성화했다. 이후 refresh 없이 실제 watchdog
SIGKILL과 별도 OFF helper의 ACK·여섯 OFF/error0·기존 cap 보존을 확인했다.

notify→main exit는 약312.4ms, notify→OFF 후처리 process exit는 약969.0ms였다.
stop 함수만의17.35ms와 전체 인계를 구분한다. 설정300ms나 all-OFF 결과를 powered
정지 시간·최악 지연 보장으로 쓰지 않는다. source와 D-Bus/trace/CRC 증거를 보존했다.

최신 두 영상과 read-only raw 관절 snapshot으로 vendor nominal mesh/FK를 대조했으나,
집게 끝과 주변 간격은 아직 확실히 식별하지 못했다. nominal FK는 실제 기계/카메라
보정이나 clearance 수용을 대신하지 않는다. 사용자에게 손끝 위치 설명 또는 시야
조정을 요청했다. 그 사실 확인 전 토크를 켜지 않으며 실제 시연·IL eligible 데이터는
계속0회다. 첫 실제 데이터셋 확보를 완료 조건으로 유지한다.
[시간 제한·실제 결과·기구 대조·미완료 범위](../validation/omx-watchdog-deadline-2026-10-16/result.md).


## 2026-10-16 후속: 카메라 제어 항목과 고해상도 시야 조사

현재 두 V4L2 장치에는 pan/tilt/zoom control이 노출되지 않는다. 지원되는1280×720
진단 프레임을 한 카메라씩 확보해 손끝 식별을 보완했다. 중복 capture를 막고 원본
producer를 멈추기 전에 독립 복구 unit을 먼저 등록했다. 두 실제 촬영 뒤 원본 명령·
환경·640×480 형식·장치별 sole producer와 ROS 소비자의 fresh frame 수신을 확인했다.

영상은 넓어졌으나 집게 양쪽 tip/face와 매트·본체 사이 간격은 여전히 확정하지
못했다. 보이는 중앙에 손/물체가 없다는 사실이나 nominal FK로 clearance를 수용하지
않는다. 요청한 손끝 위치 설명 또는 시야 조정 확인은 아직 대기 중이다. 이번 회차는
카메라 진단만 수행했고 robot bus/ON/goal 명령은 없다. 실제 시연·IL eligible 데이터는
계속0회이며 첫 실제 데이터셋 확보 목표를 유지한다.
[실제 제어 항목·프레임·복구와 남은 조건](../validation/omx-camera-clearance-2026-10-16/result.md).


### 2026-10-16 기존 카메라 저조도 자동화 실행

사용자 요청에 따라 기존 두 camera producer를 유지하며 원본 프레임 품질 측정,
bounded V4L2 후보 자동 적용, best 설정 선택, 만료되는 readiness와 종료 후 원본 복구를
연결했다. localhost viewer와 readiness user service를 Fleet PC에 실제 설치·활성화했다.
두 실제 camera-only 실행과 원본 제어값 복구, 설치 후 fresh·sole producer를 확인했다.
구형 밝기-only 판단과 uniform noise의 false pass를 회귀로 고치고 policy v2로 분리했다.

자동 조정 후에도 현재 두 영상은 관측 불충분이다. photometric 조건은 물체·파지·jaw
clearance 판독이나 motion admission이 아니다. source/원격 시험/카메라 제어/장치 구동의
증거를 구분하며 실제 시연과 IL eligible 데이터는0회다. 실제 수집·학습의 완료 기준은 유지한다.
[실행·설치·제한](../validation/omx-lowlight-automation-2026-10-16/result.md).


## 2026-10-17 후속: 환경 조건을 선행 계약으로 다루는 구조

사용자는 어두울 때의 보정만이 아니라 밝음·어둠 등 환경을 미리 고려하는 수집/학습 구조를
요구했다. 지원할 환경 범위·관측 출처·시각·판정 정책·복구 한계·실제 수용 증거를 먼저 정한다.
알 수 없는 조건을 정상으로 채우지 않으며, RGB 지표를 실제 lux나 물체 성공으로 표시하지 않는다.

환경 관측, 허용 범위 판단, 제한된 복구, 기존 owner admission, 원본/환경 이력,
에피소드 검토·분할·환경별 평가를 구분한다. 새 환경에 대응할 때 수집기마다 예외를 붙이지 않고
해당 조건의 관측·정책·복구·수용 시험을 추가한다. 지원 환경과 미검증 환경을 함께 보고한다.

| 기존 결정 | 관계 |
|---|---|
| D-427 | 기존 deploy/OMX 안에서 설치·카메라 상태 전이를 분리한다. Fleet/World/Decision/CORE 소유권을 옮기지 않는다. |
| D-429 | 외부 API/DTO 변경 없이 내부 camera policy v3와 profile hash를 고정한다. 구형 판단을 혼합하지 않는다. |
| D-430 | 환경 screening은 관절/torque 권한을 주지 않는다. 실물 admission과 stop은 기존 owner 책임이며 camera service가 우회하지 않는다. |

이번 구현은 정적 image condition과 지속적인 환경 전이·양방향 노출 복구를 분리했다.
dark/bright 후보, entry/exit 확인, 적용 완료 뒤 cooldown·host receive settling, epoch별 best,
재시작에도 유지되는 분당 attempted batch budget과 환경 이력을 추가했다. 실제 카메라에서
bounded16초 실행·원본 복구·기존 서비스 재시작 뒤 v3 서비스로 이전했고 원본 baseline은 보존했다.

데이터에는 원본/환경 이력 hash·run/profile/rig/calibration·시간 범위와 실패·개입을 묶고,
cycle/session 독립 분할과 환경별 실제 수량·held-out coverage를 보고해야 한다. 합성 증강을
실제 환경 수용으로 취급하지 않는다. 현재 episode/학습 manifest binding과 수집 executor의
환경 저하 stop 결선은 미완료다. 강조도·역광·가림·움직임·온도 등 미검증 조건은 지원으로 선언하지 않는다.
실제 시연·IL eligible 데이터는0회이며 첫 실제 데이터셋 완료 기준을 유지한다.
[환경 범위와 연결 계약](../plans/2026-10-17-omx-environment-readiness.md),
[source·원격 시험·실제 camera-only 실행과 이전](../validation/omx-environment-readiness-2026-10-17/result.md).


### 2026-10-17 불규칙 프레임 도착도 환경 조건으로 처리

암실의 실제 source 간격이 불규칙해 같은 fresh frame을 여러 번 조회하는 경우를 확인했다.
stamp·sequence·원본 품질이 같은 재조회는 WAITING_FRAME으로 분리한다. 확인/epoch/budget을
보존하되 READY·시각 이력·best·제어를 갱신하지 않으며, 실제 만료/역행/상충 품질은 계속 거부한다.
source rate를 poll rate나 설정 예시의10Hz로 가정하지 않는다.

RED→GREEN과 실제 Chromium 포함47개 원격 검사 뒤 source를 이전했다. 기존 profile·baseline·
rolling budget·환경 ledger를 보존했고 실제24 assessment의 역할48개에서 WAITING_FRAME35건,
fresh false STALE0건을 확인했다. 첫 helper의 warmup receipt 조회 실패와 자동 원복도 보존했다.
실제 시연·IL eligible 데이터는0회이며 환경 이력의 episode/학습 binding 등 완료 기준을 유지한다.
[불규칙 도착·수정·원격 검사·실제 이전](../validation/omx-environment-frame-progress-2026-10-17/result.md).


### 2026-10-17 환경 원본의 native 검토·학습 연결

native 환경 원본 log와 recorder가 선언한 Fleet host Unix ns episode 창을 데이터 파일 hash·
run/profile·rig/보정에 묶는다. 검사·분할·학습·별도 재적재에서 원본과 요약을 다시 검증하고
실패/exclude·미관측 episode·split별 영상 조건 이벤트 수를 보존한다. 기존 기록의 환경은
unrecorded이며 정상 조명으로 채우지 않는다. 프레임 identity·age·v3 수치가 확인된 새로운
관측만 알려진 영상 조건으로 집계하며 sparse transition이 연속 readiness를 입증하지 않는다.

관련82개 원격 검사와 Model PC의 실제 LeRobot 합성3episode/12frame·독립 분할·ACT2step·
별도 model/pre/post 재적재가 통과했다. 실제 닫힌 camera-only 원본37event의 형식/hash도
검증했으나 episode 창을 만들지 않았다. rig/보정/창은 선언이며 진위·물리 수용 증명이 아니다.
실제 recorder 시간 창 발행·환경 저하 owner stop·강조도 실물 수용·첫 시연과 실데이터 학습은
여전히 미완료다. [구현과 검증](../validation/omx-environment-lineage-2026-10-17/result.md).


### 2026-10-17 다음 날 실물 수집용 전체 경로 연결

기존 native owner를 사용하는 bounded teacher collector와 독립 supervisor를 연결했다.
원본 RGB·실제 관절/reference·Fleet host clock·환경 receipt·native 목표 수용/결과를 함께 보존하고,
환경/owner/수용 만료/시간·디스크 제한 실패 때 HOLD/cancel 뒤 미완료 원본을 남긴다.
단독 ROS 배치와 canonical Action 자원 lock을 확인하며 controller 시작·토크 ON·자동 복귀는 하지 않는다.
raw intake는 teacher hash와 native ledger를 다시 대조한다. 사람 검토 전에는 unknown/exclude이며
독립 session/cycle 분할 뒤 Model PC ACT 학습·새 process 재적재로 연결한다.

최종 소스 b88eee5f18 원격28개, intake/학습/전송 묶음48개 통과(선택적 기본 venv 검사1skip)와
실제 분리 LeRobot의 합성 raw journal→reader→ACT2step→별도 model/pre/post 재적재를 확인했다.
두 PC에 같은 소스293개를 배치해 각각 모의6개와 실제 runtime import가 통과했다.
Fleet 수집 unit과 private 예시는 비활성으로 유지했다. 실제 PC 간 strict SSH/scp-3 시험 파일
hash도 일치했다. native event는 소프트웨어 사실이며 물리 정지/물체 과제 성공 증명이 아니다.

실제 recorder 창·환경 중단·offline 학습 연결의 소프트웨어 구현을 추가한 것이며 실제 시연은0회다.
내일 실측 제한·집게/시야·작업공간·하중·powered stop을 확인해 acceptance를 채운 뒤 첫 수집을 한다.
강조도 실물 수용·실데이터 학습·독립 과제 성능과 G4 완료 조건은 유지한다.
[절차](../plans/2026-10-17-omx-next-day-collection.md) ·
[고정 증거](../validation/omx-next-day-collection-2026-10-17/result.md).
