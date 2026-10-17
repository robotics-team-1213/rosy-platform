# OMX 추가 준비와 접속 불가 진단

2026-10-17, D-770. 사용자는 나머지 준비도 바로 처리하도록 요청했다.
실물 시험은 내일 진행한다는 기존 범위를 유지했다. 실제 시연0회·추가 실물 명령0개다.
앞선 `b88eee5f18` 양쪽 배치와 `7d7e3d577` 로컬 main 병합 기록은
[기존 검증](../omx-next-day-collection-2026-10-17/result.md)에 있다.

## 이번 접속 결과

Fleet와 모델 PC의 SSH 시도 모두 banner exchange에서 시간 초과됐다. 원격 shell이 실행되기
전에 실패했으며 이번 환경 준비/수동 점검은 어느 PC에서도 실행 완료를 확인하지 못했다.
Windows Tailscale service와 backend는 Running, 로컬 self는 online, health 오류 목록은 비어 있었다.
승인된 private 설정의 대상만 조회했으며 모델 PC와 AI PC는 offline으로 표시됐다.
기존 SSH 설정은 Fleet/모델 접속에 AI PC를 경유한다. AI PC 직접 SSH도 TCP 접속 시간 초과였다.
Fleet의 online 표시는 있었으나 host key 검증을 유지한 직접 SSH 시도도 제한 시간 내 끝나지 않았다.
online 표시는 실제 SSH 가용성이나 전원 상태를 증명하지 않는다. 전원 차단인지 원격망 문제인지는 미확정이다.

키·계정·known_hosts·Tailscale 설정을 변경하지 않았다. 실제 카메라 조도·현재 관절 상태를
이번 시점에 새로 관측했다고 주장하지 않는다. 기존 성공한 배치를 현재 가용성으로 대체하지 않는다.
SSH 진단 로그는 외부 scratch의 `collection-ssh-diagnostic.txt`,
`finish-collection-preparation.stdout/.stderr`에 보존했다. private 접속 정보는 공개 기록에서 제외했다.

## 준비한 재개 묶음

개발 PC gitignored `private/omx-next-day-preparation-20261017/`에 다음 파일을 보존했다.
`manifest.json`은 파일 hash·기준 소스 `b88eee5f18`·원격 실행 미검증 상태를 기록한다.

- `finish-collection-preparation.sh`: 기존 카메라 env/ROS overlay에서 passive6초 영상 metadata·ROS graph·기존 프로세스와 localhost viewer/환경 receipt를 관측한다. 수집 env가 없으면 실제 기존 경로/domain과 새 OUTPUT으로 만들고 기존 파일은 보존한다. 비활성 설정의 고립 사본으로 launcher 거부와 unit inactive를 확인한다.
- `check-collection-model-ready.sh`: 기존 LeRobot 진입점의 prepare/train 도움말·소스 hash·저장 공간·수신 경로를 확인한다. 학습/장치 실행을 시작하지 않는다.
- `run-preparation.py`: 기존 private host 설정과 strict host key 검사로 한 역할만 유한 시간 실행하고 attempt별 stdout/stderr를 보존한다. 원본 준비 스크립트 hash가 다르면 거부한다.

위 묶음은 Git Bash `bash -n`과 포함된 Python/runner의 `compile()`으로 문법만 확인했다.
노트북 pytest는 실행하지 않았다. 원격 실행·실제 카메라/graph 결과·env 설치 성공은 미검증이다.
토크·직렬 버스·Action 목표·자동 복귀·수집 unit enable/start는 포함하지 않는다.
실측 범위·teacher 목표·물리 검수 사실을 자동으로 만들어 채우지 않는다.

[실행 안내](../../plans/2026-10-17-omx-next-day-collection.md)에 재개 명령·필수 env·새 세션 규칙을
보완하고 [첫 현장 기록지](../../plans/2026-10-17-omx-first-field-test.md)를 준비했다.
접속 복구 후 원격 준비·검증을 완료하고, 내일 실물 측정·정지/시야/하중 수용 뒤 첫 수집으로 진행한다.
