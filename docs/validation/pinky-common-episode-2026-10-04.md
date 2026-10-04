# Pinky 실제 녹화의 공통 Episode 연결

2026-10-04, branch `feat/learning-pipeline-closure`, 기준 SHA `573e2a024`.
[계획](../plans/2026-10-04-pinky-common-episode.md)에 따른 SOURCE/HOST 증거다.

## 실제 원본과 결과

고정 평가에 예약되지 않은 `20260930T171014Z_rosy-pinky-9dfk`의 기존 닫힌 녹화를
읽었다. 원본 MCAP 549,041,972 bytes, session metadata, 변환 video/JSONL/scan을
그대로 X 출력과 DatasetStore에 복사했다. 선언된 원본 session metadata와
변환 metadata의 일치, 시계·dt·명령 의미와 파일 SHA/bytes를 검사했다.

- Episode: `b8e76abb3e5fe9a5c4a3b490f40c99f274c407152fcc142f01d559a552cdb873`.
- Dataset: `ec59a9d7dd1e5aa224580d4ecefb08a959f977a85dbffcac474d805ee4aa9aac`.
- 2,673 frames / 2,673 recorded CORE command frames / 21 files / 554,225,036 bytes.
- camera/model/calibration/policy revision은 모두 원본 unknown에 맞춰 null.
- task/action outcome과 judge는 unknown, Action/Attempt correlations는 빈 목록.
- common task는 녹화 reason이며 원본 task_id를 mission/Action 식별자로 만들지 않았다.
- environment real / clock ros_system은 변환 입력의 명시적 provenance 선언이다.

원본·고정 eval·기존 OMX dataset·정책을 바꾸지 않았다. DatasetStore 등록을 별도
프로세스에서 재독출했고 독립 리뷰도 같은 실제 snapshot을 읽었다.
증거는 `X:/DevTemp/rosy-learning-audit-20261004/pinky-episode-readback.json`이다.

## 공통 계약과 승격 gate

wheel 0.1.4의 stdlib Pinky profile은 닫힌 세션·identity·영상 bytes/크기·frame 수,
capture/log 시계·finite m/s/rad/s 명령·causal lookback dt·stamped 관측 규칙을 검사한다.
원본 metadata·stream·unknown 결과를 공통 Episode에 연결한다. Pilot은 아직 거부한다.
OMX를 Pinky로 이름만 바꿔 검사를 우회할 수 없다.

정책 승격과 과거 승격 조회는 등록 Dataset의 모든 Episode profile/robot/environment가
정책과 맞아야 한다. 독립 리뷰가 검증 뒤 재독출하는 사이의 무해시 변조 우회를 발견했고,
동일한 검증 Episode 객체 안에서 호환성을 검사하도록 수정했다. 재현 시험 RED→GREEN.
모델/관절/camera 설치·runtime owner admission 전체를 이 gate로 인증하지 않는다.

## 검증

- Pinky curation: 8 passed.
- 최종 registry/artifact/selector/Pinky: 89 passed, interleave 회귀 포함.
- 독립 최종 dataset/registry/Pinky: 38 passed, interleave 회귀 포함, 남은 지적 없음.
- architecture ownership/import/module: 51 passed.
- harness/document placement: 65 passed; lint 0 errors, 기존 warning 26개.
- isolated Python 3.12 wheel: dependency 없음, numpy/Pillow/torch/mcap 미로드,
  실제 2,673프레임 검사 통과.
- wheel SHA-256: `042dae2a54ace0b52715f22a81c7c7d39b7a32bec8dd86197e217fa3cce75073`.
- CI full matrix와 FULL_SUITES에 Pinky curation 추가; remote CI는 실행하지 않았다.

MCAP↔sidecar 변환 진위, 영상 pixels·scan 내용, 정책 학습·독립 과제·owner 실행·Fleet
결과 join은 미검증이다. 기존 실제 녹화를 호스트에서 읽은 증거이며 새 물리 주행,
장치 설치, shadow 전달/rollback 수용 또는 과제 성공 증거가 아니다. 전체 목표는 active다.
