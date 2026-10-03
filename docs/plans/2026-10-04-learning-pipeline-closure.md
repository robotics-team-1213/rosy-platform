# ROSY learning pipeline closure implementation plan

**Goal:** Pinky·OMX의 데이터 수집, 학습, 평가, 모델 전달, 안전한 실행과 Fleet 결과를 증거로 연결한다.
**Architecture:** D-434의 모델 PC/관제 PC 역할을 유지하고 기존 perception store/intake/watch를 먼저 연결한다. 행동 정책은 D-427의 공통 Episode·PolicyArtifact·owner 계약을 구체화한 뒤 OMX SIM에서 시작하고 Pinky로 확장한다.
**Tech Stack:** Python, PyTorch/ONNX, LeRobot export, systemd, ROS 2 Jazzy, Fleet SQLite.

## 점검 기준

2026-10-04 모델 PC 조회에서 CUDA 사용 가능, 412프레임 데이터셋과 3에폭 기록, 760프레임 intake pass를 확인했다. 고정 평가 세트·model-watch 시스템 유닛·설정은 없었다. 실행 device를 기록하지 않은 기존 학습 run을 GPU 학습 수용으로 해석하지 않는다. 관제 PC의 Fleet/Vision/proxy는 healthy였다. 기존 계정·주소·키는 private 자료만 사용한다.

## M1 — 인식 평가와 섀도 전달

1. `learning/training/perception/dataset/labels.py`의 wall role을 D-373과 맞춘다. 기존 version은 보존하고 새 라벨 version을 만든다. `test_d379_evalset.py`의 export 결과 검사로 실패를 재현한다.
2. 학습에 사용하지 않은 실제 녹화 세션에서 LiDAR/trajectory 라벨을 생성한다. `build.py --eval-set`으로 내용 해시가 고정된 평가 세트를 만들고 학습 세션 비겹침을 검사한다.
3. 기준 모델을 평가하고 클래스별 값과 라벨 출처·보정의 한계를 기록한다. 출처 null을 임의로 채우지 않는다. 합성 입력·val 값으로 실제 평가 합격을 대체하지 않는다.
4. `intake.py`/`rosy_ml doctor`/watch 설정을 연결한다. READY → intake → accepted/rejected의 중복·손상·재시작을 검증한다.
5. 검토 가능한 서비스 설정·설치 후보를 만든 뒤 모델 PC에 설치한다. 필요한 sudo가 허용되지 않으면 설치 후보와 실제 부족 조건을 제시한다.
6. 지정 로봇에서 기존 허용 범위의 shadow 전달·status·rollback을 확인한다. 주행 모드와 operational paint pointer는 별도 장치 승인 절차를 따른다.

## M2 — 반복 학습 job

수거 → catalog → autolabel → build → train → export → intake를 잇는다. 각 단계는 실행 SHA·dataset/eval hash·모델 revision·상태·오류·산출물을 기록한다. 미수거 데이터 삭제 금지, 불완전 READY 금지, 세션 비겹침을 유지한다. GPU 학습과 Isaac을 동시에 실행하지 않는다.

## M3 — OMX 정책 첫 고리

공통 Episode·PolicyArtifact·승격·owner 실행 계약을 후속 ADR로 구체화한다. 기존 LeRobot export에서 모방학습과 offline/SIM 평가를 연결한다. policy의 행동 후보는 기존 owner/Safety Guard를 지난다. 물리 과제 결과는 Action 성공과 독립적으로 판정한다.

## M4 — Pinky 주행 정책과 Fleet 결과

관측·v/omega 행동·주기·stale·reset·개입·HOLD 계약을 정하고 sim/replay에서 검증한다. Fleet mission/action/policy revision·결과를 Episode와 연결한다. ER2 피드백은 재학습이나 device command 권한과 구분한다. Isaac 5.1 importer/ROS graph 수용도 별도로 확인한다.

## 검증과 종료

로컬은 관련 suite와 fast gate만 실행한다. 전체 suite/ARM64 artifact는 프로젝트 CI를 따른다. SOURCE/LOCAL/ROS-SIM/ARTIFACT/DEVICE/FIELD를 구분하고 실제 물리 동작·운영 활성화는 기존 승인 경계를 유지한다. 같은 PC의 파일 존재나 컨테이너 healthy를 실물 성공으로 취급하지 않는다.

첫 변경 검증: wall role의 eval manifest 검사 RED 확인 후 autolabel·dataset·evalset·training contract 회귀 83 passed, 3 skipped(Windows torch/onnxruntime 부재). 모델 PC의 실제 평가 실행은 후속 단계다.
