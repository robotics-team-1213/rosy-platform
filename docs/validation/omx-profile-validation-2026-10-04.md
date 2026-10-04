# OMX Episode 본문 검증

2026-10-04. branch `feat/learning-pipeline-closure`, 기준 commit `828cfdf01`.
[계획](../plans/2026-10-04-omx-profile-validation.md)의 SOURCE/HOST 검증이다.

## 변경

공통 계약 wheel 0.1.3의 OMX profile은 원본 완료 상태·explicit operator task outcome,
Gazebo 시계·fps 간격·50 ms skew, 관절 순서·rad 목표·제한·goal ID·duration,
samples/events/image SHA를 검사한다. RGB PNG의 크기·CRC·전체 압축 스트림·행 길이와
filter를 stdlib로 검증한다. 8/16 bit 및 Adam7 입력을 지원한다.
task outcome은 원본 operator 기록이며 독립 과제 성공 인증이 아니다.

공통 Episode의 device/task/calibration/outcome과 observation/action/events 참조는
검증된 원본 시연에 연결된다. DatasetStore는 복사 전·후·재등록·승격 조회 시 이를 검사한다.
본문 검증기가 없는 Pinky/Pilot profile은 등록을 거부한다. profile 이름 변경으로
OMX 검증을 우회하던 경로를 독립 리뷰에서 발견해 수정하고 회귀 시험을 추가했다.
SQLite 조회 연결도 명시적으로 닫아 Windows 파일 핸들을 GC에 맡기지 않는다.

offline curation은 `rosy.contracts.learning.omx`를 직접 import한다.
D-427 Q6의 learning→middleware 위반 항목을 제거했다. runtime recorder와
device wheel 설치는 유지하며 전체 wave 2b 또는 runtime 승인 완료를 의미하지 않는다.
worktree의 기존 AGENTS.md는 사용자 지침에 따라 갱신하지 않았다.

## 실제 데이터 재검증

기존 immutable dataset
`8dda786b742bebbd5eae5453f2db60534a22984c5e1943a99de92bb7f0b608bf`의
6개 OMX SIM Episode, 75프레임, 234파일이 새 본문 검증을 통과했다.
원본·dataset·policy revision은 바꾸지 않았다. 별도 readback은
`X:/DevTemp/rosy-learning-audit-20261004/omx-profile-readback.json`이다.
새 SIM 실행이나 실제 장치 동작 증거가 아니라 이전 SIM 녹화의 HOST 재검증이다.
기존 ACT 정책은 여전히 unregistered/rejected이며 승격하지 않았다.

## 검사

- 독립 리뷰 최종 본문·curation·registry·공통 metadata: 66 passed, 1 skipped (Python 3.14).
  skip은 이 환경에 없는 LeRobot round-trip이다.
- native Python 3.12 curation: 21 passed, skip 없음. 실제 LeRobot v3 export를
  다시 열어 state/action/video를 확인했다. third-party deprecation 경고 13개.
- 학습 OMX/기존 recorder: 20 passed.
- ownership/import/module 구조: 51 passed.
- harness/document placement: 65 passed, 기존 경고 26개. lint 0 errors/26 warnings.
- Python 3.12 isolated wheel import: dependency 없음, Pillow/torch 미로드,
  실제 저장 데이터 75프레임 검증 통과.
- wheel SHA-256: `7b884e9eb05fdd706af2882488483dbbf3ea5a6458050ff1c312f0e325048fae`.
- 독립 리뷰의 profile 우회·SQLite 핸들 문제 수정 후 남은 지적 없음.

장치 설치·ARM64 build·remote CI·owner 실행·physical shadow/rollback은 이 단계의
증거에 포함되지 않는다. Pinky/Pilot 본문 검증·Fleet join과 독립 정책 과제 수용은 후속 작업이다.
