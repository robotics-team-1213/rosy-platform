## D-446 모델 PC도 서명 코드 자동 업데이트에 포함하고 작업·GPU 환경·모델 승격을 분리한다

**Status:** Accepted (2026-10-04, 사용자 결정). 설계와 구현 진행 승인이다. 실제 설치·자동 전환·장기 운용 수용은 각각 증거로 확인한다.

### Context

D-412는 로봇 런타임, D-441은 관제 PC의 사이트 스택을 갱신한다. D-434의 모델 PC는 데이터 수집·라벨·학습·변환·평가·store와 D-373 모델 전달을 맡지만 코드 갱신 경로가 없다. 확인 당시 모델 PC의 소스는 이전 D-434 커밋이고 model-watch timer는 미설치였다. GPU 사용률은 작업 경계의 증거가 아니다.

### Decision

1. 세 역할 모두 버전 관리 대상으로 둔다. 릴리스와 적용 시점은 역할별로 나눈다. 모든 장비가 매 push마다 같은 SHA로 전환해야 한다는 규칙은 두지 않는다. D-427의 learning/operations 경계를 유지하며 새 최상위 폴더를 만들지 않는다.
2. 1차 모델 PC 자동 업데이트의 payload는 `learning/training/perception/`의 추적된 코드·설정·노트북과 그 import 의존성 `middleware/perception/control/`, `contracts/foundation/core_common/`, 자동 라벨 기하 보정에 필요한 `middleware/apps/device/pinky/profile/config/camera_nominal.yaml`이다. 이 경로는 같은 source commit에서 Git archive로 가져오며 저장소의 상대 경로를 보존한다. 런타임 노드·CORE·모터 서비스를 모델 PC에서 시작하지 않는다. 작업 중인 Git checkout은 갱신하지 않는다. 그 checkout의 perception 경로에 커밋하지 않은 수정이 있으면 전환을 보류하고 파일은 그대로 둔다.  후보는 commit별 별도 디렉터리로 준비하고 `current` symlink만 원자적으로 전환한다. 설치된 업데이트기와 작업 실행기는 후보 밖에 두며 후보가 자신을 갱신하지 않는다.
3. 후보 manifest는 `rosy-model-code/1`, source commit, 단조 증가 sequence, archive SHA-256, 현재 학습 환경 fingerprint를 포함한다. 전용 공개 키로 Ed25519 서명을 검증하고 archive digest와 안전한 파일 경로를 검증한 뒤에만 후보 코드를 검사한다. 기존 site candidate 서명 envelope 구현을 재사용하지만 모델 코드 전용 키와 payload type을 요구한다. 서명 개인 키는 운영자 PC에만 두고 모델 PC에는 공개 키만 등록한다.
4. 자동 적용은 서명된 후보 inbox의 READY 완료 폴더만 소비한다. 후보 생성·서명·전달은 명시적 승인된 커밋에 대해 운영자 릴리스 명령으로 수행한다. `main`에 있다는 이유로 자동 승인하지 않는다. CI 후보 생성과 서명 PC 자동 발행 연결은 후속 범위이며 이 단계의 자동화는 등록된 후보의 소비·전환이다.
5. 작업 실행기와 업데이트기는 같은 flock 파일을 배타적으로 잡는다. 실행 시작 시 source commit·환경 fingerprint·명령의 식별 정보를 receipt에 기록하며 인수 원문·비밀은 기록하지 않는다. 자식 작업도 lock을 상속한다. GPU 작업도 직렬화하여 D-434의 Isaac/학습 동시 실행 금지를 지킨다. GPU compute process 또는 사용률, 관리되지 않는 기존 learning/Isaac 작업 프로세스, hold 파일, 환경 불일치, 커밋하지 않은 perception 수정이 있으면 적용하지 않는다. exec는 커밋하지 않은 로컬 스크립트가 서명 릴리스와 다르면 실행하지 않는다. 깨끗한 이전 checkout은 새 서명 코드 실행을 막지 않는다. 그 수정은 브랜치로 커밋해 개발 PC로 가져온 뒤 새 서명 후보가 되어야 실행된다. 불명확하거나 관측 실패한 상태도 보류한다. 기존 작업을 중지하거나 checkpoint를 삭제하지 않는다.
6. 활성화 전 Python 소스 구문, 필수 라이브러리 import, 작은 CUDA 연산과 실제 CLI 진입점의 `--help` import 검사를 확인한다. 후보와 작업은 Python isolated mode로 ambient PYTHONPATH/user-site fallback을 차단한다. 전환 후 같은 검사에 실패하면 이전 symlink로 복귀하고 실패 sequence를 기록하여 자동 재시도하지 않는다. 고장·전환 중 재시작은 durable pending 기록으로 복구한다. sequence는 되돌리지 않으며 낮은 후보로 자동 downgrade하지 않는다.
7. Python·PyTorch·CUDA·드라이버·Isaac·OS 패키지를 자동 설치·업그레이드하지 않는다. 설치된 학습 환경 fingerprint를 후보와 대조한다. 환경 변경은 별도 가상환경에서 GPU·export·intake 검증 후 운영 전환하며 잠금 파일로 버전을 고정한다. Isaac 5.1과 학습 환경 분리, Isaac Lab HOLD는 D-434/D-427을 유지한다.
8. 데이터셋·store·평가 자료·checkpoints·작업 결과·SSH 등록·비밀·모델 hold는 후보 밖에 보존한다. 기존 스크립트의 ROOT/data 기본값을 보존하기 위해 설치된 controller만 후보 ROOT/data를 등록된 work_dir/data에 연결한다. data는 archive에 포함하지 않고 외부 디렉터리의 내용·소유자·등록을 바꾸지 않는다. 작업 cwd도 외부 work_dir이다. Python isolated bootstrap에는 후보의 perception/model/dataset/training/sensing/foundation 경로만 추가한다. 모델 watch도 작업 실행기를 통해 같은 lock과 고정 source를 사용한다. 운영 watch 설정은 별도 파일로 유지하고 doctor 통과 후 timer를 활성화한다. 모델 전달은 D-373의 평가→shadow까지만이며 주행 모델 선택은 D-205 P3 절차를 유지한다.

### D-497 지도 생성 작업 추가

D-497 추가 범위(2026-10-07, 사용자 모델 PC 고려 요청): 서명 코드 묶음에 Vision의
`__init__.py`, `lane_map.py`, `map_register.py` 세 파일과 isolated import 경로를 추가한다.
작업 이름 `camera_lane_map.py`가 기존 잠금 실행기로 지도 초안만 생성한다(2026-10-08부터 perception 래퍼 없이 실행기의 고정 대응표가 서명된 Vision `lane_map.py`를 바로 실행한다, D-427 §2). 다른 Vision
서비스 파일은 포함하지 않으며 고정 controller는 후보 밖에서 별도 갱신한다. 기존 후보의
복귀·생성과 GPU 환경은 유지한다. 모델 PC 설치·작업 실행 수용은 별도 증거로 확인한다.

### Alternatives

- 사용 중인 checkout에 주기적 git pull/pip upgrade: 작업 도중 코드·환경이 달라지고 복귀와 재현이 불명확하여 기각한다.
- 모델 PC는 수동 갱신만 유지: 역할 간 source drift가 남아 기각한다.
- OS/GPU 환경까지 한 후보로 일괄 갱신: 재부팅과 호환성 검증이 필요하여 1차에서 제외한다.

### Consequences and acceptance

후보 공급 승인과 호스트 적용을 나눠 관리한다. 로컬 테스트 통과는 CI·GPU 작업·학습 모델 운용 수용이 아니다. 승인 후보 적용·busy 보류·잘못된 서명/환경 거절·전환 실패 복귀·재시작 복구를 실제 모델 PC에서도 검증한다. model-watch doctor와 실제 모델 평가·shadow 전달 증거는 코드 updater의 설치 증거와 따로 기록한다. 실제 주소·계정·경로 설정은 private 자료에만 남긴다.
