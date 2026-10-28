## D-897 AI PC와 모델 PC에서 격리된 시뮬레이션 학습 작업을 병렬 실행한다

**Status:** Accepted (2026-10-27, 사용자 요청: 두 PC 모두 학습용 시뮬레이션을 구성해 병렬 작업). 설치·동시 실행의 실제 통과 여부는 별도 검증 기록을 따른다.

### Context

모델 PC에 Lab 3 Newton 학습 환경을 구성했고 Sim 6.2 후보의 의존성·종료 정리를 복구 중이다. 사용자는 AI PC에도 학습용 시뮬레이션을 구성해 서로 다른 작업을 동시에 실행하도록 요청했다. 확인한 두 PC는 각각 RTX 5080 Laptop 약 16GB VRAM, RAM 32GB, Python 3.12.3, 드라이버 580.178.04다. GPU와 호스트 메모리를 합친 단일 장비로 취급하지 않는다.

### Decision

1. 두 호스트에 같은 commit·lock의 Lab v3.0.0 Newton/MJWarp 학습 환경을 분리 설치한다. 기본 병렬 단위는 호스트별 독립 작업·seed·출력이다. 이 결정은 DDP·다중 노드 gradient 동기화 구현을 뜻하지 않는다.
2. D-516의 AI PC 추론 전용 규칙 중 **격리된 오프라인 시뮬레이션 학습을 금지하는 부분만** 이 요청 범위에서 개정한다. 운영 추론 환경·고정 프로파일·서비스를 학습 venv와 섞지 않는다. 학습은 승인 프로파일을 자동 교체하거나 승격하지 않는다. 모델 PC의 데이터·독립 평가·registry 소유권은 유지한다.
3. AI PC의 Fleet 원장·admission·ROS·장치 Action·최종 명령 권한은 추가하지 않는다. 관제 PC는 학습 대상이 아니다. 제품 시뮬레이션 catalog의 model 역할 경로도 자동으로 바꾸지 않는다.
4. 각 호스트의 기존 시험 예약과 GPU 소유를 확인한다. 다른 시험은 종료하지 않는다. 사용자는 첫 병렬 학습 검증 동안 AI PC의 rosy-v11-sam-worker와 rosy-ollama를 일시 중지하고 이후 원래 실행 상태로 복원하도록 승인했다. 설치 완료 뒤 검증 직전에만 중지하고, 실패·timeout 때도 복원 경로를 둔다. 이 승인을 이후 모든 학습의 영구 중지 허가로 확대하지 않는다. native simulation placement lease가 있는 호스트는 해당 lease도 획득한다. GPU 작업은 호스트당 하나를 기준으로 하며 CPU·RAM 예산, timeout, 소유 cgroup 종료와 산출물 회수를 각각 검증한다.
5. 첫 공통 수용은 공식 Cartpole의 GPU 물리 실행과 짧은 PPO 학습이다. 두 호스트의 실제 학습 구간이 겹치는지 시각으로 확인한다. 이 결과는 OMX 일반화·카메라·실물 수용이나 분산 학습 성능의 증거가 아니다. Sim 6.2 RTX 통합은 Newton 기반 병렬 학습과 분리해 판정한다.
6. 드라이버·야간 재부팅·운영 SDK binding·활성 서비스는 이번 설치에서 바꾸지 않는다. 새 작업은 호스트별 rosy-test의 정해진 run·venv 경로를 쓰며 원래 실패를 덮어쓰지 않는다.

### 기존 구조 결정과 관계

| 결정 | 이 변경과의 관계 |
|---|---|
| D-427 | 학습 소스·평가·registry는 learning 소유를 유지한다. 호스트를 추가해도 설치 패키지를 장치 payload에 넣지 않는다. |
| D-429 | 오프라인 학습 배치 추가이며 Fleet·World·Decision·장치 실행의 책임 경계를 바꾸지 않는다. |
| D-430 | CORE와 OMX 실행 권한·안전 게이트를 유지한다. 시뮬레이션 학습 결과만으로 실제 명령을 허용하지 않는다. |

### Consequences

같은 task를 seed나 설정으로 나눠 두 PC에서 실행할 수 있다. 데이터셋·평가 분할·코드·lock 지문과 호스트 역할을 각 결과에 묶는다. 운영 추론이 GPU를 쓰는 동안 AI PC 학습은 대기한다. 16GB GPU 두 개가 32GB 단일 GPU를 제공하는 것은 아니다.

### Verification

호스트별 설치·전체 의존성 검사, CUDA·물리·PPO·checkpoint·소유 종료 관측을 보존한다. 동시 실행은 두 독립 보고서의 학습 시작·종료 시각과 작업 지문으로 확인한다. 연결 불가·외부 GPU 점유·설치 실패·skip을 성공으로 합산하지 않는다.

**Related:** [D-434](D-434-model-pc-and-site-pc-roles.md), [D-516](D-516-offline-decision-model-replay-boundary.md), [Lab 3 환경](../../learning/envs/isaac/lab3/README.md).
