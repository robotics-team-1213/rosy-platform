# 녹화부터 반복 학습 job 연결 검증

2026-10-04 KST. [GPU 학습 job](training-job-2026-10-04.md)에 앞단의
선택적 harvest → 출처 catalog → autolabel → immutable build를 연결했다.
이 기록은 새 recording_job.py의 SOURCE/LOCAL 증거다. 모델 PC의 실제 녹화로
이 전체 명령을 재실행한 증거와 구분한다.

## 구현과 실행 계약

`python training/recording_job.py <config.json> --out <job-dir>`.
`--prepare-only`면 학습 전에 dataset ref와 training-config 경로를 반환한다.
전체 실행은 `model-job/`의 기존 train_job을 호출하고 부모의 model 단계도 기록한다.
실패 시 재시도 이력이 남고, 품질 거절은 terminal이며 부모도 rejected가 된다.
재개 때 자식 job을 다시 조회해 source/output SHA와 현재 inbox/accepted 위치를 확인한다.

입력은 완료된 MCAP session 또는 bag_to_video MP4+metadata JSON+sidecar JSONL이다.
video의 session identity와 선언된 scan NPZ를 검사하고 원본 파일 SHA를 기록한다.
원본 raw·driver 근거가 없으면 null을 유지한다. 모델 예측/CVAT 검수 대기 mask를
자동 정답으로 넣지 않는다. 기존 shared catalog를 덮어쓰지 않고 job별 source/curated
catalog를 보존하며 dataset hash·split·라벨 경로를 연결한다.

harvest는 기존 스크립트를 호출한다. token file·SSH identity·known_hosts·host alias를
필수로 받고 CORE idle 확인을 우회하는 assume_idle 옵션은 받지 않는다.
고정 평가를 해시로 검증하고 겹친 session은 라벨 생성 전에 거절한다.
입력/gate/source 변경에는 새 job이 필요하다. 성공 단계는 해시 확인 후 건너뛰며
부분 라벨은 새 attempt 경로에서 다시 만든다. 라벨 실행 중 원본 변경도 build 전에
거절한다. 원본 삭제나 로봇 motion/watcher 호출은 없다.

## 검증 범위

새 시험은 중단 후 라벨 재개, 파일 변조, session identity, heldout 제외,
harvest 인자와 idle 실패의 중단/재시도, 입력 변경, 실제 라벨러/빌더 왕복,
처리 중 원본 변경, 부모 model 단계의 실패/재시도/READY 상태를 다룬다.
harvest/trainer 경계 시험은 주입된 함수이며 실제 장치 수거·GPU 실행 증거가 아니다.
관련 회귀 94 passed/1 skipped, 추가 parent terminal reject를 포함한 신규 10시험
전부 통과. 구조·문서 배치 시험 48 passed/1 skipped. generate 완료,
lint 0 errors/기존 26 warnings.
recording_job.py SHA:
`8fe61cfa4c82686cadc681a5b700c3c621be26ffe7d63f4359d577cbec4b5d57`.

왕복 시험은 X 드라이브에서 두 개의 합성 MP4와 odom sidecar를 생성하고
실제 autolabel.py CLI 및 build_auto_dataset을 호출했다. build 필터 이후 2프레임
(train 1/val 1), store dataset SHA:
`15c6bd04ebaeedced2822769eda800e4281107ef215d66ddf91598185a7f402c`.
단계 catalog/label-0/label-1/build는 각각 attempt 1이며 두 번째 prepare에서
반복 처리 없이 결과가 같았다. mask 크기 240x320, heldout session 비포함,
내용 해시와 원본 video 보존을 확인했다. 이는 라벨 정확도나 정책 학습 수용이 아니다.

로컬 산출물은
`X:/DevTemp/recording-job-affected-final-20261004/` 및
`X:/DevTemp/recording-job-terminal-20261004/`에 남겼다.
모델 PC 재실행은 Tailscale SSH의 추가 인증 요구로 대기한다. 기존 GPU 후보의
성공 증거를 새 recording job의 실제 데이터 실행 증거로 대신하지 않는다.
추가 인증 후 최종 소스를 다시 복사해 SHA를 확인하고 실제 녹화로 반복 job을 실행한다.

전체 목표의 잔여 gate: 장치 idle/수거 실증, 실제 데이터의 앞단부터 READY 실행,
operator hold를 존중한 shadow/rollback, system timer 권한, 검수된 신호/물체 학습,
공통 Episode/PolicyArtifact/승격/owner 실행, OMX/SIM/Pinky/Fleet 결과 연계.
DEVICE/FIELD·운영 주행 활성화는 미수용이며 목표는 active다.
