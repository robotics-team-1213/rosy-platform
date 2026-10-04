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
운영 주행 활성화는 이번 변경으로 승인하지 않는다.
전송 이력 API/UI, 정책/owner/Fleet 결과의 인증된 연결과 DEVICE/FIELD 증거도 남는다.

## 후속: pointer history 동기화와 PC 전용 SSH

history append 뒤 기존 flock 안에서 GNU `sync -f history.jsonl`을 실행한다.
파일이 속한 filesystem을 동기화하며 실패하면 exit3과
`history durability unknown`을 반환한다. 이때 pointer는 이미 바뀌었을 수 있다.
기존 HOLD/승격 승인 경계와 pointer 선택은 유지한다.

- 다섯 action의 append→sync 순서를 검증했다. Linux scratch의 실제 rollback
  shell에 sync-f 실패를 주입하여 exit3, 변경된 pointer, 유지된 HOLD와 history를
  확인했다. 실제 로봇 변경이나 전원 차단 시험은 아니다.
- 모델 PC Linux 관련 6 suites는 208 passed, 0 skipped, exit0다. coreutils9.4.
  로컬 archive와 원격 result SHA256이 일치한다:
  `0148a90b1f0b60304cb200bf1ba19cc357e8fda409d8e1da8cfe1949f3b2705f`.
  독립 호스트 검토는 77 passed, 19 skipped이며 blocking finding이 없었다.
- 관제 OpenSSH 활성 상태를 확인하고 authenticated Tailscale 경로에서 읽은
  host key와 inventory의 장비 모델·계정·주소를 대조했다. 서버가 전용 키의
  정확한 fingerprint를 수락한 publickey 인증까지 검증했다. 기본 별칭은
  pinned LAN SSH이며 `rosy-site-pc-ts`는 기존 Tailscale 경로다.
  모델 PC의 기본 LAN/전용 키 접속은 유지한다.
- 관제 model-watch unit은 아직 not-found다. 관리자 설치·실서비스 검증과
  실제 로봇 shadow/rollback, DEVICE/FIELD 수락은 남아 있다.

private 증거는 X:/DevTemp/rosy-learning-audit-20261004 아래
`model-history-sync-linux-v1`과 `site-dedicated-key-openssh-v1`에 보존했다.

문서 계약 검사에서는 82 checks가 통과하고 full lint 하나가 실패했다.
기존 HEAD 로그의 경로 안 bare CR이 read_text에서는 LF로 바뀌지만 git 출력에서는
유지되어 append-only 비교가 실패하는 것을 변경 전 HEAD로도 재현했다.
이번 추가 기록의 schema와 원래 byte 보존은 별도로 통과했다. 초기 한글 기록의
인코딩 손상과 새 heading/필드 오류는 복구했다. 기존 역사 기록은 수정하지 않았다.
baseline 근거는 `history-sync-doc-baseline.json`이며 full lint green을 주장하지 않는다.
