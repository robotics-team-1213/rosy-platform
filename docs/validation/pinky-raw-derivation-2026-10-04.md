# 기존 Pinky 녹화의 원본 메시지 대조

2026-10-04. `feat/learning-pipeline-closure`, 기준 `7a28608cb` 이후 변경.
[계획](../plans/2026-10-04-pinky-raw-derivation.md)의 SOURCE/HOST 검증이다.

ROS 2 CDR/MCAP의 단일 namespace·표준 schema·CRC를 검사하고 camera 시각,
최신 causal 명령·odom, 같은 capture stamp의 첫 eligible JSON 관측, scan NPZ의
float16 ranges·int64 stamp·float32 dt·기하를 기존 sidecar에 대조한다.
DatasetManifest/Episode 전체 파일 closure를 검증 전후 검사한다. JSON boolean과
number도 구분한다. 영상은 전체 decode의 프레임 수와 크기를 확인한다.

기존 Dataset `ec59a9d7dd1e5aa224580d4ecefb08a959f977a85dbffcac474d805ee4aa9aac`,
Episode `b8e76abb3e5fe9a5c4a3b490f40c99f274c407152fcc142f01d559a552cdb873`에
`prepare_behavior.py`를 직접 실행했다. 12개 MCAP, camera/영상 2,673프레임과
cmd_vel·odom·line/observation·scan 각 2,673프레임이 대응했다. skip 0.
원본·dataset revision을 변경하지 않았다. 새 촬영이나 장치 동작 증거가 아니다.

산출물은 `X:/DevTemp/rosy-learning-audit-20261004/pinky-behavior-input-v2/`이다.
`raw-verification.json` 2,331 bytes, SHA-256
`7a2335943ff3da17aad8f7ceeadad5ba659d8ce79976c5be5e150d5f660f38c1`.
이전 v1은 실행 이력으로 보존했다. 준비 CLI는 기존 pass 보고서를 신뢰하지 않고
검증기를 직접 실행하며 실패 시 출력 디렉터리를 만들지 않는다.

- Python 3.12 native curation: 26 passed, skip 없음. 실제 CDR/MCAP/video fixture 포함.
- 독립 리뷰: 같은 26 passed. dataset source 누락 및 JSON 타입 혼동을 RED 재현,
  수정 후 GREEN. 최종 남은 material findings 없음. 큰 실제 녹화 검증은 중복 실행하지 않았다.
- Python 3.14 curation/registry: 50 passed, 6 skipped (MCAP host package 없음).
  위 native 시험에서 같은 MCAP 시험을 모두 실행했다.
- ownership/module 구조: 51 passed. 문서/harness: 89 passed, 기존 경고 26개.
- 추가 공통 계약/folder 배치: 27 passed, 1 skipped (호스트 LeRobot 없음).
- harness lint: 0 errors/26 기존 warnings. CI는 Pinky 시험 job에 호스트 의존성을
  설치하도록 수정했으나 remote CI는 실행하지 않았다.

행동 입력은 `research_input_only`, `split=unassigned`다. action은 기록된 CORE
최종 속도(m/s·rad/s)이며 expert intent/미래 목표가 아니다. pixel provenance,
expert action 의미, fixed behavior eval, task acceptance, camera profile holds를 유지한다.
정책 학습·승격·owner 실행·Fleet 과제 성공·DEVICE/FIELD 수용은 미완료다.
호스트 MCAP/numpy/OpenCV 의존성은 stdlib 계약 wheel에 추가하지 않았다.
