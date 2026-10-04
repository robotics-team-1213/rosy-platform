# Model shadow 전달·rollback 시도의 운영자 측 기록

2026-10-04. [관제 accepted 경로](site-champion-acceptance-2026-10-04.md) 다음 단계다.
로봇의 실제 shadow 전달과 rollback 수용은 아직 미확인이다.

## SOURCE

`learning/training/perception/model/delivery_journal.py`와 `deliver.py`를 연결했다.
endpoint/SSH 설정 검증 후 CLI 시도마다 고유 attempt ID/독립 JSONL 파일을 만든다.
명령 시작과 각 network step 시작 전에 파일 flush/fsync를 완료한다. Linux에서는
새 파일의 parent directory도 fsync한다. 초기/step 기록 실패 시 network를 시작하지
않고 기존 history error code 3을 반환한다. Linux의 기본 directory는 사용자
state 영역, Windows는 X:/DevTemp/rosy-model-delivery-journal이다.
`--journal-dir` 또는 `ROSY_MODEL_DELIVERY_JOURNAL_DIR`로 전용 directory를 지정한다.

push는 model validation, prepare, transfer, pointer operation을 기록한다.
검증에 이미 사용한 model manifest/intake report SHA를 연결하며 해당 파일을
감사 목적으로 다시 읽어 다른 bytes를 바인딩하지 않는다. rollback 등도 같은
시도/단계/종료 기록을 사용한다. status는 읽기 전용 시도로 기록한다.
명령문, identity/known-hosts 경로, stdout/stderr, key/token 내용은 저장하지 않는다.
target 식별자가 포함되므로 이 기록은 private 운영 자료다.

CLI 종료 분류인 `command_outcome`과 원격 결과의 `outcome`을 구분한다.
timeout/예외 또는 변경 단계의 비정상 종료는 원격 변경 결과 `unknown`을 유지한다.
완료 기록 없이 끊긴 시도 역시 unknown이다. remote command의 exit0은 device/task
수용이 아니며 해당 두 verified flag는 false다. 기존 SSH error exit 매핑과
intake/HOLD/lock/서명/작업별 slot 경계, remote pointer script는 변경하지 않았다.
이 로컬 이력은 receipt 인증, 외부 tamper-proof anchor 또는 owner 실행 권한이 아니다.

## HOST / Linux / 실제 읽기 전용 연결

- Windows 전달/rollback/watcher 관련 6 suites: 184 passed, 18 skipped.
- 최종 현재 호스트의 6 suites와 문서 placement/layout: 215 passed, 3 skipped.
- 독립 전달/작업/journal 회귀: 72 passed, 18 skipped. fsync 초기·step 실패 시
  network 호출0, timeout unknown 보존, 기존 HOLD 경계와 민감 값 미기록을 확인했다.
- Linux 모델 PC에서는 Windows의 shell skip을 포함한 전달3 suites 89 passed.
  6 suites의 v2 source archive는 service unit을 빼먹어 201 passed/1 missing-file
  failure였다. 입력 archive를 보완한 v3 결과는 별도 evidence로 보존한다.
- 보완한 v3의 Linux 전달/rollback/watcher 6 suites는 202 passed, exit0다.
  보존 archive SHA와 원격 result의 archive SHA를 로컬에서 다시 대조했다.
- HOST fake runner로 push prepare→transfer→pointer 기록과 별도 rollback 시도를
  확인했다. 실제 장치의 포인터 변경 증거가 아니다.
- 별도 실제 host process는 durable started/step_started 뒤 READY handshake를
  확인하고 강제 종료했다. 유효한 두 JSONL 줄은 남고 finished는 없었다.
  network/robot 명령0이며 원격 결과 unknown으로 판단한다.
- 두 로봇의 실제 read-only SSH/status는 시간 초과 exit78이었다. 수정된 v2 기록은
  `command_outcome=failed`, `outcome=unknown`, 장치/과제 verified false다.
  현재 shadow/HOLD/rollback 포인터를 읽지 못했다. 원격 변경 작업은 호출하지 않았다.

실행 증거는 X:/DevTemp/rosy-learning-audit-20261004 아래
`delivery-journal-linux-v1/v2/v3`, `delivery-journal-status-v1/v2`,
`delivery-journal-hard-stop-v1`에 있다. 첫 시험의 default directory에 생성된 합성
이력은 보존·격리했으며, 이후 pytest autouse fixture는 시험별 tmp_path로 기록한다.
합성 성공 이력을 운영자 기록으로 해석하지 않는다.

## 남은 gate

관제 watcher의 최신 소스 설치·실제 서비스 계정/저장 경로 검증은 아직 필요하다.
로봇 전용 key/host pin과 현재 연결을 확인한 뒤 accepted 모델의 실제 shadow 전달,
loader 관측, rollback pointer/stop readback을 확인해야 한다. operator HOLD 해제나
운영 주행 활성화는 이번 변경으로 승인하지 않는다. 로봇 측 pointer history의 fsync,
전송 이력 API/UI, 정책/owner/Fleet 결과의 인증된 연결과 DEVICE/FIELD 증거도 남는다.
