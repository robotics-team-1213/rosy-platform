## D-834 웹·CLI 공통 Isaac 실험 run과 소유 실행 경계

**Status:** Proposed

## Context

사용자는 학습 관리 센터와 CLI가 같은 실험 설정·결과를 공유하도록 설계를 승인했다. 기존 `/learning`은 결과 링크와 Perception 고정 owner 제어를 제공하지만, Isaac 실험 실행기와 항만 물리 적층 제어기는 아직 없다. D-826은 실험 목적·단계·증거를 정하며 이 결정은 반복 실행의 기록과 실행 책임을 다룬다.

## Decision

1. `learning/envs/isaac/`의 allowlisted catalog·run 저장소·전용 실행 모듈을 웹과 CLI가 공유한다. 첫 실행은 OMX-F 모델 import 검사다. 물리 집기·적층·회수·양팔 복구는 선행 구현·판정이 연결되기 전까지 거절한다.
2. 불변 입력 snapshot과 SHA-256, 전체 source SHA, 자산·판정기 지문, seed, run/request ID, 상태 revision, 결과·산출물 해시를 보존한다. 동일 요청 재전송은 같은 run, 다른 입력은 충돌이다. 새 실행은 부모 run을 연결하고 이전 결과를 유지한다.
3. 승인된 외부 data root의 파일을 사용한다. 원자적 상태 갱신·revision 검사, 불변 최종 결과, regular file·root·크기·해시 검증을 적용한다. 최종 증거와 비원자적 관찰, 실행 종료와 과제 성공을 구분한다. 실패·중단·UNKNOWN을 숨기거나 자동 재시작하지 않는다.
4. 후속 실행기는 모델 PC의 승인 SDK Python과 동일 Linux 계정의 model-code `work.lock` → learning `gpu.lock`을 사용한다. 실제 child 종료까지 두 잠금을 유지한다. SDK·GPU·계정·소유 프로세스가 불명확하면 새 실행을 거절한다. 관리 밖 GPU 프로그램까지 시스템 전체에서 차단한다고 주장하지 않는다.
5. 웹은 기존 앱·계정·공통 셸을 확장한다. 서명된 웹 프로세스에 외부 Isaac 코드를 동적 import하지 않고, source/binding이 고정된 로컬 실행기에 좁은 요청을 전달한다. HTTP가 path·argv·host·unit을 선택하지 않는다. 기존 Perception retry·로봇 명령 계약은 유지한다.
6. CORE·OMX 최종 writer, Fleet admission·원장, Episode 검수·학습/평가 분리·승격 책임을 유지한다. import 성공·시뮬레이션 점수는 물리 파지·장치 수용·정책 배포 승인이 아니다. D-823 Leader 개입·협응 동작도 이 작업에서 열지 않는다.

| 기존 결정 | 관계 |
|---|---|
| D-427 | 기존 learning·tools·curation holder를 사용하며 새 최상위 구조·장치 payload를 만들지 않는다 |
| D-429 | 데이터·계약·실행·웹 역할을 유지하고 source 경로를 host/writer 권한으로 해석하지 않는다 |
| D-430 | 로봇 안전 권한을 넓히지 않는다. 후속 safety 변경은 독립 검토와 기존 관문을 따른다 |
| D-745·D-792 | 기존 고정 학습 owner와 앱을 유지하고 SIM 실행 책임을 구분한다 |
| D-795·D-826 | host 통신 경계와 실험 증거 등급·진입 기준을 유지한다 |

## Consequences

브라우저와 CLI에서 같은 run의 설정·실패·결과를 확인할 수 있다. 연결 단절·중지 실패·부분 결과를 보존해야 하므로 exit code만으로 성공을 표시할 수 없다. SDK·동일 계정의 잠금·고정 source/binding이 준비되지 않으면 실행은 HOLD다.

이번 기록 단위는 catalog·run 저장소와 host-only 계약 시험이다. GPU 실행기·CLI·웹·실제 SDK 검증은 [구현 계획](../plans/2026-10-21-sim-learning-workspace.md)의 후속 단위다. Proposed 기록이나 파일 추가를 구현 완료·ROS-SIM·DEVICE·FIELD 수용으로 해석하지 않는다.

## Amendment by D-857 (2026-10-24)

SIM 실험 화면은 Rosy Learning 「학습」 메뉴 아래에 둔다. 실행 경계는 그대로다. [D-857](D-857-rosy-learning-product-definition.md)
