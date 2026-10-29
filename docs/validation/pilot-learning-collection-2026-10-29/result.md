# Pilot 수집 → 모델 PC → Learning 검수 대기 연결

2026-10-29. 제품 소스 `66e86cb0fb4f0e65e55bfe35d10b591169c3986a`, 시작 main `b0a31796b455f3136b98ef39ff3ea8270b574aca`. 작업 브랜치 `fix/pilot-learning-collection`. 이 기록은 코드·기존 녹화 처리·시험 증거이며 새 실물 조종이나 운영 배포 수용이 아니다.

## 변경

- `fetch_http --local-only`가 로봇 연결·자격 없이 기존 원본의 manifest·파일 크기·해시를 확인하고 변환을 복구한다. 전송 경로의 TLS·Operator·정지 판정과 기존 반환 코드를 유지한다.
- 새 영수증은 MP4와 sidecar 해시를 함께 보존한다. 기존 영수증과 다른 바이트를 새 성공으로 덮어쓰지 않는다. 예전 영수증에 MP4 해시가 없는 경우 현재 영상의 digest를 준비본에 기록할 뿐 독립 원본 검증 권한을 부여하지 않는다.
- 변환은 임시 폴더에서 마친 뒤 게시한다. 이전 부분 출력은 별도 디렉터리에 보존하고 sidecar를 마지막에 게시한다. 기존 출력을 채택하려면 source session·메타데이터 프레임 수·조작 짝이 맞아야 한다.
- `pilot_review.py`가 기존 `pixel_label_job.prepare_sources`와 `review_ingest`를 연결한다. 원본·출력 지문을 보존한 PNG/video/catalog를 만들고 선택한 기존 작업 공간에 pending으로 등록한다. 사람 정답·승인·이력을 덮어쓰거나 학습·모델 활성화를 시작하지 않는다.
- 수신 entry도 승인된 서명 model-code에서 실행한다. 승인 URL의 private 설정, 독립 로컬 처리 timer와 공용 flock을 추가한다. 실제 설치는 하지 않았다.

## 원격 시험

모든 pytest는 커밋 SHA를 승인된 시험 PC에 보낸 실행이다. 노트북 pytest는 실행하지 않았다. 로그 루트는 `C:/DevTemp/pilot-collection/`이고 파일 지문은 `reports.sha256`에 남긴다.

| 소스 / 로그 | 실제 결과 | 범위 |
|---|---|---|
| `0b2a341785`, `red-ai/run-1.txt` | 11 failed | 없는 local-only·pending 연결·unit, MP4 없는 성공을 재현 |
| `711fe23770`, `green/run-1.txt` | 49 passed | 첫 수정 집중 시험 |
| `a86e6d03ef`, `integrity-red/run-1.txt` | 2 failed / 1 skipped | MP4/sidecar 변경 재승인 반례. MCAP 의존성 없는 회차의 codec skip은 통과로 세지 않음 |
| `a86e6d03ef`, `codec-red/run-1.txt` | 1 failed | AI PC의 FFmpeg 부재로 실패. 제품 반례의 증거로 사용하지 않음 |
| `a86e6d03ef`, `codec-red-site/run-1.txt` | 1 failed / 0 skipped | pinned raw·실제 FFmpeg에서 부분 MP4가 재변환을 막는 반례 |
| `0700d26c43`, `publication-red/run-1.txt` | 2 failed / 0 skipped | 메타데이터 없는 출력 채택과 게시 중단 반례 |
| `66e86cb0fb`, `final-codec/run-1.txt` | 55 passed / 1 skipped, exit 0, NEW 0 | 모델 PC, `--test-tools pinky-raw`, 실제 MCAP·FFmpeg. skip은 별도 활성화하는 기존 자료 수용 시험 |
| `66e86cb0fb`, `final-real-recording/run-1.txt` | 1 passed / 0 skipped, exit 0, NEW 0 | 아래 실제 기존 녹화 수용을 명시 실행 |
| `0a4579edfd`, `affected/run-1.txt` | 13,605 passed / 1,280 skipped / 205 warnings, exit 0, NEW 0 | 공식 affected 선택 전체: `middleware/core/gateway/test/test_protocol_version_alignment.py test` |
| `66e86cb0fb`, `final-affected/run-1.txt` | 2 failed / 13,605 passed / 1,280 skipped / 205 warnings, exit 1, NEW 2 | 같은 전체 선택. 아래 OMX fixture 지터 실패를 제외하거나 통과로 바꾸지 않음 |
| 원본 main `b0a31796b4`, `baseline-omx/run-1.txt` | 32 passed / 0 skipped, exit 0 | 변경 전 OMX 파일의 독립 대조. 과부하 전체 실행을 재현했다는 뜻은 아님 |

집중 명령은 다음과 같다. 일반 환경과 pinned raw 환경을 혼동하지 않는다.

```text
python tools/remote/remote_pytest.py --test-tools pinky-raw --log-dir <log-dir> -- test/learning/perception/test_fetch_http.py test/learning/perception/test_pilot_review.py test/test_pilot_collection_units.py test/test_account_tls_renew.py -q
```

공식 전체 선택은 다음 파이프로 전달했다. `affected` 모드의 root 전체 시험이며 canonical FULL 행렬을 실행했다고 주장하지 않는다.

```text
python tools/harness/rosy_harness.py affected --base b0a31796b455f3136b98ef39ff3ea8270b574aca --json | python tools/remote/remote_pytest.py --log-dir <log-dir> --affected-json -
```

## 기존 실제 녹화 처리

모델 PC의 기존 Pilot 녹화 한 건을 원위치에서 읽었다. raw·sidecar·영상은 수정하지 않았다. 준비본과 별도 검증 작업 공간은 `~/rosy-test/evidence/pilot-collection-20261029-final/`에 보존했다.

- 19개 exact PNG/video frame을 준비하고 19장 모두 pending으로 등록했다.
- 같은 입력 재실행에서 `added: 0`, 총 프레임 19장을 확인했다.
- catalog SHA-256: `45f1e9ed59983cf7b1c73b1c5f59d3c00312c6eb07ab19998b4e99277828f219`.
- 운영 Learning 검수 DB는 변경하지 않았다. 원본 영상 독립 검증·사람 승인·학습·평가·승격을 완료했다는 증거는 아니다.

## 전체 회귀의 OMX fixture 후속

`66e86cb0fb`의 실패는 `test_reached_step_records_measured_errors`, `test_published_camera_models_are_hashed_raw_evidence_only_when_changed`였다. 이벤트에 `capture cadence exceeds accepted jitter; no frame interpolation`이 기록됐다. 해당 생산 코드와 시험 파일은 이 작업의 시작 main과 같았다. 실제 저장 지연과 스케줄링 중 어느 지연이 얼마였는지 정량 재현하지 않았으므로 특정 디스크 장애로 단정하지 않는다.

두 시험은 실시간 시계로 합성 영상 시각과 완료 동작을 비교했다. 같은 파일의 기존 성공 시험은 이미 가상 시계를 공유하고 있었다. `d2d68c3346`에서 그 시계를 명시 fixture로 추출해 두 시험에 공유했다. 생산 지터 제한·파일 쓰기·해시·도달 단언은 그대로이며, 실제 지연을 측정하는 slow-intent-storage 시험은 실시간 시계로 유지했다. 독립 읽기 검토에서 보완의 단언·시계 범위를 확인했다. 이 보완의 최종 전체 실행 결과는 후속 기록으로 추가한다.

초기 모델 PC RED 대기 회차와 저자원 AI PC의 `verified-affected` 대기 회차는 다른 PC 재배정 뒤 해당 작업의 신원을 확인하고 취소했다(exit 143). 실행 성공으로 세지 않는다. 첫 전체 회귀의 임시 파일 잔류 경고도 원 로그에 보존하며 다른 작업의 임시 파일을 지우지 않았다.

## 적용·수용 경계

독립 코드 검토에서 발견한 영수증 재승인과 중단 게시 문제는 반례를 추가한 뒤 수정했다. `66e86cb0fb` 생산 변경과 `d2d68c3346` fixture 보완의 재검토에서 남은 중요 지적은 없었다. 검토자는 읽기만 했고 원격 결과는 이 실행자가 확인했다.

로컬 main 착지·push·서명 후보 공급·운영 unit/env 배치·service 재시작·APK 갱신·새 실물 조종/녹화는 하지 않았다. 모델 PC의 기존 수신 타이머는 로봇 이름 해석 실패 상태이며 로봇 두 대 SSH도 닿지 않았다. 주소를 추측하거나 TLS를 해제하지 않았다. 배포 절차·환경 결속·rollback은 `deploy/model_pc/README.md`를 따른다. 새 실물 녹화의 전체 경로는 연결 복구 후 별도로 수용해야 한다.

CE: 해당 없음 — 복구·무결성·중복 방지·fixture 시계 판단은 코드·회귀·기존 운영 문서에서 확인할 수 있다. 운영 접속 실패는 해결 교훈으로 기록하지 않고 우산 작업 기록의 미해결 상태를 유지한다.

## 최종 추가 기록 · `d2d68c334679b37d79fb1ec9c10c5b50933d5fe9`

- 공식 affected 전체 선택을 모델 PC에서 실행해 **13,602 passed / 1,285 skipped / 205 warnings, exit 0, NEW 0**을 확인했다. 로그는 `verified-affected-model/run-1.txt`다. 앞선 AI PC 회차와 호스트별 skip 수가 다르므로 skipped를 통과로 합치지 않는다. 이 회차는 4분 44초였고 runner가 보고한 임시 lock/socket 잔류 경고는 원 로그에 보존했다.
- 같은 SHA에서 `pinky-raw`와 실제 기존 녹화 환경을 명시해 Pilot 집중 4파일과 OMX 수집 32시험을 함께 실행했다. **88 passed / 0 skipped, exit 0, NEW 0**이다. 로그는 `verified-focused/run-1.txt`다. codec·실제 자료 수용·가상 시계 보완을 이 최종 커밋에서 함께 확인했다.
- 집중 명령은 위 4파일에 `test/test_omx_collection_session.py`를 더하고 실제 자료 시험의 `ROSY_PILOT_*` 환경을 전달한 실행이다. 데이터·주소·자격은 명령 예시로 고정하지 않고 기존 private 경로를 사용했다.
- 별도 실제 자료 수용은 `~/rosy-test/evidence/pilot-collection-20261029-verified/`에 보존했다. 실행 후 독립 read-only 재독출에서 catalog 19행, DB pending 19장, 출력 전체 해시 일치, 원본 manifest 불변과 기존 raw 영수증 불변을 확인했다. catalog SHA는 앞선 `45f1e9ed…728f219`와 같다. 재실행 추가 0장과 기존 사람 검수 보존 단언도 통과했다.
- `git diff --name-only 66e86cb0fb..d2d68c3346`은 `test/test_omx_collection_session.py` 한 파일이다. 생산 코드는 앞선 검토·실제 자료 수용과 동일하고 마지막 변경은 시험 시계 fixture다. 독립 재검토에서 단언·생산 지터 한계·실시간 지연 시험 유지와 남은 중요 지적 없음을 확인했다.
- 기존 운영 Python과 현재 승인된 서명 코드의 의존 import, FFmpeg 가용성은 읽기 전용으로 확인했다(`model-preflight.txt`). 새 `pilot_review.py`가 현재 승인 릴리스에 없음을 확인했으며, 이를 우회해 운영 설치하지 않았다. main 착지와 D-446의 명시 커밋 승인·서명 후보 공급, 실제 workspace/classes 결속 및 서비스 적용은 별도 승인·후속 실행으로 남는다.

최종 판정은 **코드·검증된 기존 자료의 pending 등록 연결 수용**이다. 새 실물 조종·수신과 운영 서비스 적용 수용은 아니다.

## 기록 정합성 후속 · `e0a68bef19c14f10d004c95dad40f6c2788e5db0`

생산 코드와 시험은 `d2d68c3346` 그대로이고 운영 문서·검증 기록·생성 색인을 커밋한 뒤, 모델 PC에서 harness·문서 배치·폴더·host manifest·collection unit 계약을 **129 passed / 0 skipped, exit 0, NEW 0**으로 확인했다(`record-contracts/run-1.txt`). 로그 지문 14개를 다시 대조해 불일치 0건을 확인했다. 로컬 harness lint는 0 errors/38 warnings였다. 완료 시점의 모델 PC DNS 재확인에서도 두 등록 로봇 이름은 여전히 해석되지 않았다. 새 실물 수집과 운영 적용을 완료한 것으로 판정하지 않는다.

## 승인된 운영 적용 후속 · 2026-10-29

사용자의 “나머지도 처리해줄래” 승인으로 로컬 main 착지와 등록 모델 PC 배포를 진행했다. 앞 절의 미적용 판정은 그 시점의 기록이며, 아래 적용 결과로 갱신한다. GitHub push와 새 실물 동작은 수행하지 않았다.

- D-446 정상 서명 경로로 sequence **44**, source **`709ebf8b8e293836c4dcb62a53e78c594f401a1f`**를 적용했다. 등록 공개키와 로컬 공개키의 SHA 일치를 확인했고, signature·archive·환경 지문·CUDA health 검사를 통과했다. archive SHA는 `942d0764689a784247d7125a8f4bdfa3d429dd5a8e8a4c28ba10f7f5a54b1e83`, 환경 지문은 `24eb783be68765fa71e753d940f1b93c2845ad721d3d96a19c9e47e838034933`이다. 기존 key/config와 Python 패키지는 유지했다.
- 설치 전 별도 SQLite online backup과 unit/controller/config 백업을 `~/rosy-ml/pilot-collection-deploy/44-709ebf8b8e/backup/`에 보존했다. 자동 등록 대상은 기존 주행 workspace이며, 격리된 후보 Learning Center DB와 합치지 않았다. 실제 workspace의 클래스 SHA **`345815d706c5209e6e11adf5c572b5a4f6074af0451b5ef7fe4ff92d8f7e4f2f`**와 일치하는 기존 YAML을 사용했다. 저장소 기본 YAML로 기존 클래스 결속을 바꾸지 않았다.
- 운영 설치 점검에서 unit의 직접 실행이 model-code work lock을 공유하지 않는 문제를 발견했다. `7b3f2d9db1`의 RED에서 3실패를 확인하고 `a017e601d5`에서 기존 `rosy_model_code.py ... exec dataset/...` 소유자를 사용하도록 수정했다. 네 파일 원격 회귀 **209 passed / 0 skipped, exit 0, NEW 0**(`lock-green/run-1.txt`)와 독립 검토를 확인한 뒤 설치했다. 설치된 controller 4파일도 승인 소스에서 공급해 새 job mapping을 포함했다.
- 이어 GPU 작업이 있는 정상 `WorkBusy` 보류가 exit 3으로 반환됨을 실제 관측했다. 두 job의 helper는 exit 3을 반환하지 않는다. `0739f64d88`에서 2실패를 확인한 뒤 `c71326b078`의 unit은 명시적인 `3 75`만 정상 건너뛰기로 처리한다. 네 파일 원격 회귀 **209 passed / 0 skipped, exit 0, NEW 0**(`busy-green/run-1.txt`)와 독립 검토를 통과했다. 네트워크·무결성·설정 오류의 exit 1/2는 계속 실패다.
- 설치된 unit은 `c71326b078`의 archive와 byte hash가 일치한다. archive의 CRLF를 LF로 정규화하면 Git blob과도 일치한다. fetch unit SHA `1da62485af97ee9d84d82c598a4e6b0d7bd1ed3dd16cb7526d7160c3cdbc8dbf`, process unit SHA `e61f1f3efa3406c2efe403ceb2af8fc1f0777ab7bc80a41b1203942a10e9a95a`이다. SSH 세션의 runtime dir 누락으로 최초 `systemd-analyze --user verify`가 실패했으나, 기존 UID의 runtime dir를 지정한 재검사는 exit 0이었다. 사용자 unit과 두 타이머를 활성화했다.
- 운영 read-only 재검증에서 원래 53프레임의 review/status/version, mask, events, pixel_events digest가 모두 불변이었다. 두 기존 Learning 서비스는 active다. fetch는 수집 잠금 충돌(exit 75), process는 기존 GPU 작업(exit 3)으로 건너뛰었고 두 타이머는 active다. **운영 신규 프레임은 아직 0장**이며, 보류를 처리 성공으로 세지 않는다. 서명 current는 sequence 44를 유지하지만 updater의 최근 상태는 다른 GPU 작업 때문에 `held`다.
- 후보 Center에 주행 workspace 탐색 링크를 추가하려던 시도는 exact-unit installer guard가 거절했다. 즉시 원래 unit을 복원하고 active를 확인했다. 새 링크 파일도 운영 state에서 백업 영역으로 옮겼다. 기존 [exact-unit 교훈](../../solutions/deployment/learning-center-upgrade-needs-the-identical-unit-first-2026-10-23.md)에 해당하며 guard를 우회하지 않았다.
- 두 등록 로봇은 pinned SSH 재확인에서도 timeout, 모델 PC의 두 mDNS는 해석 실패다. 주소·CA·토큰을 추측하거나 교체하지 않았다. 모델 PC 설치는 완료했지만 **새 실물 조종 → 수신 → 운영 pending 등록 수용은 미확인**이다.

후속 로그는 `C:/DevTemp/pilot-collection-deploy/` 아래에 보존했다. `rollout-verification.json`은 주소·자격·라벨 본문을 제외한 운영 관측 영수증이다. 착지는 기존 `tools/land_async.py --tests auto` 대기열로 진행하며, 통과·완료는 해당 gateway 로그에서 따로 확인한다.

CE: 해당 없음 — 실행 소유자·보류 코드 판단은 수정 코드·회귀·README에, exact-unit 복구는 기존 교훈에 있다. 중복 교훈은 추가하지 않았다. GPU 보류와 로봇 접속 장애는 미해결 운영 상태로 남긴다.
