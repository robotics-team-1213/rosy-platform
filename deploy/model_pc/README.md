# Model PC Decision 평가

## Pinky Pilot 녹화 자동 수신 (D-534)

`rosy-pilot-fetch@.timer`는 모델 PC 사용자 세션에서 종료된 Pilot 녹화를 10분마다 확인한다. 수신은 기존 `fetch_http.py`가 CORE의 정지 판정, 장치 TLS, Operator 권한, 원본 SHA-256, MP4 변환과 조작 짝 검사를 수행한다. 이 작업은 원본·영상까지이며 픽셀 초안, 사람 승인, 학습은 별도 단계다.

설치 전 모델 PC의 `~/rosy-ml/bin/fetch_http.py`와 checkout의 `learning/curation/perception/bag_to_video.py`를 확인하고, 이 버전의 수신기를 모델 PC에 배치한다. 각 로봇 인스턴스의 장치 CA를 `~/rosy-ml/<id>-ca.pem`, 읽기 전용 Operator 토큰을 `~/.config/rosy/pilot-<id>.operator-token`에 배치한다. `~/.config/rosy/pilot-<id>.env`에는 `SINCE_ID=<첫 자동 수집 세션 ID>`를 넣는다. 기존 세션에 조작 짝이 없어 실패가 반복되는 것을 막는 경계다. 파일 내용과 로봇 주소를 Git에 넣지 않는다. 한 로봇의 예:

```bash
mkdir -p ~/.config/systemd/user
cp deploy/model_pc/rosy-pilot-fetch@.{service,timer} ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user start rosy-pilot-fetch@9dfk.service
systemctl --user status rosy-pilot-fetch@9dfk.service --no-pager
systemctl --user enable --now rosy-pilot-fetch@9dfk.timer
journalctl --user -u rosy-pilot-fetch@9dfk.service -n 80 --no-pager
```

`9dfk`는 설치 예시의 mDNS ID이며 현장 로봇 ID를 사용한다. `start`에서 정지·토큰·TLS·해시·변환 결과를 확인한 뒤 타이머를 켠다. 변환이 실패하면 검증된 raw 폴더를 남기고 다음 주기에 로컬 변환을 재시도한다. 성공 영수증은 사이드카 해시·영상 존재·조작 짝을 확인한 뒤에만 만든다. 로봇의 원본과 승인 상태는 이 타이머가 변경하지 않는다.
물리 로그인 코드로 받은 Operator 토큰은 만료된다(D-193 기본 7일). 만료 전에 새 코드로 재페어링하고 타이머의 마지막 성공 시각을 확인한다.

[D-527](../../docs/adr/D-527-decision-test-host-boundaries.md)의 L0 실행 위치다. 개발 로컬 PC는 `test/test_decision_replay.py`와 lint·푸시 검사를 수행한다. 모델 PC는 사람 정답이 있는 독립 세트로 텍스트 Laya/Kev/규칙 기준선을 비교하고, VLM은 별도의 영상·LiDAR 정답 세트로 평가한다. AI PC의 역할은 승인된 고정 버전의 적재·추론 스모크와 watchdog 확인이다.

1. 사건을 비식별화하고 수집 세션 단위로 개발/독립 세트를 분리한다. 텍스트 JSONL은 `id`, `state`, `instructions`, `criteria`, `expected` 계약을 따른다. VLM 프레임·정답은 텍스트 세트에 섞지 않는다.
2. 모델 PC에서 고정 모델·토크나이저·서버 revision을 기록하고 로컬 서버를 `127.0.0.1`에만 연다. 같은 독립 세트와 질문/선택지를 각 후보에 사용한다. `python3 tools/decision_replay.py <independent-set.jsonl> --model <model-id> > <receipt.json>`으로 텍스트 후보를 재생한다. 도구의 기본 endpoint는 loopback이다.
3. receipt의 세트 SHA-256, 정답·예측·오류·기권·p95를 보존하고 모델 revision, 서버 버전, GPU 사용량, 질문 버전과 함께 평가 기록을 만든다. 사람 정답이 없으면 연결 시험으로만 표기한다. VLM에는 D-492의 별도 V0/V1 평가 관문을 적용한다.
4. 평가 통과 뒤 고정 ModelProfile **후보**와 digest, 최소 비식별 스모크 입력만 AI PC로 전달한다. 실제 전달 방식·인증·승인 스키마가 정해지기 전에는 자동 배포하지 않는다. AI PC는 자체 평가로 후보를 바꾸거나 승격하지 않는다.

실제 장치 주소·계정·비밀, 원본 사건, 모델 가중치와 실행 로그는 이 공개 저장소에 넣지 않는다. 현재 Model PC의 GPU 인식은 확인했으나 Decision 전용 평가 환경과 사람 정답 세트는 아직 확인되지 않아 L0은 HOLD다.

## v13 검수 앱 코드 릴리스

승인된 모델 코드 후보가 적용된 뒤에는 [D-561](../../docs/adr/D-561-model-review-ui-signed-code-follow.md)의 별도 사용자 타이머가 검수 UI도 버전별 릴리스로 전환한다. 모델 PC에서 설치된 D-446 `state.json`의 현재 sequence를 `MINIMUM_SEQUENCE`에 기록한다. 기존 화면보다 오래된 후보가 처음 실행될 때 활성화되지 않게 하는 기준이다. `REVIEW_HOST`와 `REVIEW_PYTHON`은 현재 `rosy-review-v13.service`의 `--host`와 실행 Python이다. 상태 폴더에 `learning-collaboration.json`이 있으면(계정 연동) 검수 앱은 HTTPS 뒤 loopback으로만 열리므로 `REVIEW_HOST=127.0.0.1`이다. 값이 다르면 업데이터가 계정 연동이 빠진 서비스 파일을 쓰거나 거절한다. 활성화 전에 `install_review_release.unit_contents(...)`가 지금 서비스 파일과 같은 내용을 만드는지 확인한다. 먼저 타이머를 한 번 수동 실행해 `waiting for a newer accepted model-code release`를 확인한 뒤 활성화한다.

```bash
install -m 0755 deploy/model_pc/auto_review_release.py deploy/model_pc/install_review_release.py ~/rosy-ml/bin/
install -m 0644 deploy/model_pc/rosy-review-release-update.{service,timer} ~/.config/systemd/user/
printf 'REVIEW_HOST=%s\nREVIEW_PYTHON=%s\nMINIMUM_SEQUENCE=%s\n' '<current --host>' '<current review Python>' '<current-model-code-sequence>' > ~/.config/rosy/review-release.env
chmod 600 ~/.config/rosy/review-release.env
systemctl --user daemon-reload
systemctl --user start rosy-review-release-update.service
systemctl --user enable --now rosy-review-release-update.timer
```

새 서명 후보의 자동 적용 뒤 `systemctl --user status rosy-review-release-update.service`와 `readlink -f ~/rosy-ml/review-v13-code/current`를 대조한다. 후보 발행·서명은 D-446에 따른다. 이 타이머는 `main`의 새 커밋만으로 검수 화면을 바꾸지 않는다.

검수 앱은 모델 PC의 `~/rosy-ml/review-v13-code/releases/<release>/`에 완전한 실행 소스를 보존하고, 사용자 서비스 `rosy-review-v13.service`는 `~/rosy-ml/review-v13-code/current` 링크를 실행한다. 검수 기록인 `~/rosy-ml/review-v13-drivable/state`는 릴리스 밖에 둔다. 기존 런타임 폴더를 다시 풀거나 교체해도 `current`가 가리키는 화면은 바뀌지 않는다. 배포 결정은 [D-545](../../docs/adr/D-545-model-pc-review-versioned-release.md)을 따른다.

첫 전환에서는 **현재 모델 PC에서 실제 실행 중인, 검수 스튜디오가 적용된 코드 폴더**에서 코드 전용 입력을 만든다. 그 폴더에는 과거 `state/`가 들어 있을 수 있으므로 반드시 제외한다. 이후에는 검증한 정확한 Git 커밋의 전체 검수 앱 소스를 모델 PC의 별도 준비 폴더에 전송한 후 같은 명령을 사용한다. `review_app.py`, `review_app_web/`, `shared/web/` 및 해당 모듈의 Python import 경로를 포함해야 한다. 소스 폴더에는 DB, 영상, 모델 가중치나 비밀을 넣지 않는다. 릴리스 이름은 출처를 식별할 수 있게 고정하며 재사용하지 않는다. 전송 자체는 자동 갱신되지 않으며, 이 명령을 실행해야 화면이 전환된다.

```bash
# 첫 전환: 모델 PC에서 기존 실행 코드만 별도 입력으로 준비한다.
mkdir -p /tmp/rosy-review-code-<release-id>
rsync -a --exclude=/state/ <current-code-directory>/ /tmp/rosy-review-code-<release-id>/

# 모델 PC의 검수 서비스 사용자 세션에서 실행. 스크립트는 저장소에서 모델 PC로 복사해 둔다.
python3 ~/rosy-ml/bin/install_review_release.py <release-id> \
  --source /tmp/rosy-review-code-<release-id> \
  --state ~/rosy-ml/review-v13-drivable/state \
  --python ~/rosy-ml/.venv/bin/python \
  --host <model-pc-private-ip> --port 8774

# 이전 릴리스로 명시적으로 되돌릴 때 (재복사·DB 변경 없음)
python3 ~/rosy-ml/bin/install_review_release.py <previous-release-id> \
  --host <model-pc-private-ip> --port 8774
```

설치기는 소스의 필수 파일, DB 분리, 복사본 해시, Python import를 확인한 뒤 링크와 서비스 유닛을 전환한다. `/api/workspace`와 `/pixels`가 응답하지 않으면 이전 링크와 서비스 유닛으로 되돌리고 오류를 반환한다. 첫 전환 전의 서비스 유닛은 `~/rosy-ml/review-v13-code/rosy-review-v13.service.before-managed`에 남긴다. `REVIEW_RELEASE.json`의 해시는 릴리스 입력 파일 묶음의 내용 해시이며 Git 커밋이나 학습 모델의 승인을 뜻하지 않는다. 릴리스와 검수 DB를 함께 지우거나, 이 절차 밖에서 `current` 링크를 덮어쓰지 않는다. state 안의 `learning-collaboration.json`·`omx-center.json`·`learning-control.json`·`review-ai.json`·`workspace-links.json`이 있으면 대상 앱이 지원하는 옵션만 서비스에 붙이고, 예전 릴리스로 되돌릴 때는 그 앱이 모르는 옵션을 뺀다. `workspace-links.json`은 설치 때 일반 파일·스키마를 먼저 확인한다.

### Account 프로젝트별 설치 (D-757)

두 설치 CLI는 `--service <safe-name.service>`를 받으며 기본값은 기존 `rosy-review-v13.service`다. 다른 표준 `review_app.py` 서비스는 고유 `--root`, `--state`, `--port`, `--service`를 함께 지정한다. 사용자 유닛 경로·재시작·최초 백업 이름은 지정한 서비스에 맞춘다. 별도 구현의 데이터셋 서버에는 이 설치기를 적용하지 않는다. 자동 갱신 CLI에도 같은 `--service`와 프로젝트 경로를 지정해야 하며 기존 v13 타이머 설정은 v13에만 적용된다.

`state/learning-collaboration.json`이 있으면 새 릴리스와 보관 릴리스 전환 모두 `--collaboration`을 유지한다. 앱은 `--host 127.0.0.1`로 실행하고 정확한 공개 HTTPS origin은 기존 승인 프록시에서 제공한다. 이 모드에서는 무인증 `--decisions-port`를 만들지 않는다. 이미 결속한 설정 파일이 사라지거나 보관 코드가 collaboration/중앙 Account를 지원하지 않으면 전환을 거부한다. 인증을 끄는 rollback은 지원하지 않는다. Account DB·키·HF 연결·검수 DB는 코드 릴리스 밖의 기존 비공개 경로에 남긴다.

```bash
python3 ~/rosy-ml/bin/install_review_release.py <release-id> \
  --source <accepted-code-directory> --root <project-code-root> \
  --state <existing-project-state> --python <project-venv>/bin/python \
  --host 127.0.0.1 --port <project-loopback-port> --service <project-service>.service
```

`--source`는 링크가 없고 `--root`·`--state` 밖에 있는 폴더여야 한다. 승인된 D-446 릴리스 폴더는 `data` 링크가 있어 그대로 쓰지 못하므로, `data`를 뺀 복사본을 `--root` 밖의 형제 폴더에 만든다([절차](../../docs/solutions/deployment/learning-center-upgrade-needs-the-identical-unit-first-2026-10-23.md#installing-an-accepted-d-446-model-code-release-with-install_review_releasepy)).

협업 readiness는 무자격 `/api/workspace`의 **401**, `/api/accounts/options`의 활성화·프로젝트 ID·중앙 Account 모드 일치, `/accounts`의 **200**을 확인한다. 실패하면 이전 링크와 유닛으로 복구한다. 이 검사는 사용자 로그인·권한·회수나 프록시 TLS 수용을 대신하지 않는다. 실제 자료를 바꾸지 않는 일관 복사 상태의 로그인/권한/회수/브라우저 검사와 공개 HTTPS 확인은 별도 기록한다.

같은 DNS 이름의 서로 다른 HTTPS 포트에서 중앙 Account 프로젝트를 열 수 있다. 세션·Account PKCE·HF OAuth 쿠키는 신뢰 설정의 프로젝트와 공개 origin별 이름을 쓴다. 기존 고정 이름의 중앙 앱 쿠키는 읽지 않으므로 전환 후 한 번 다시 로그인한다. 중앙 Account를 사용하지 않는 기존 모드는 쿠키 이름을 유지한다. 상세 계약은 [Account protocol](../../docs/reference/rosy-account-protocol.md#앱-수신-세션)을 따른다.

## 검수에서 학습 owner로 연결 (D-742)

검수 설치기는 기존 화면 port+10000에 loopback GET `/api/decisions`만 연다. 8774 화면은 18774의 현재 결정 조회와 연결된다. 사설 화면 바인딩·쓰기 token·원본 DB는 유지한다.

같은 PC의 bridge 설정은 기존 설정에 `transport: local`과 pinned `authority`를 사용한다. `source`는 검수 state의 exports, `remote_reviews`는 별도 pipeline reviews 경로, `peer`는 `local`, `interval_s`는 10, `max_attempts`는 3이다. authority.endpoint는 `http://127.0.0.1:18774/api/decisions`, workspace_id는 실제 화면에서 읽은 ID다. SSH 기본 전달 설정은 바뀌지 않는다. 같은 receiver에는 bridge writer 하나만 구성한다.

private config는 `~/.config/rosy/review-pipeline/bridge.json` 및 `pipeline.json`에 둔다. pipeline.json은 기존 ReviewPipeline의 `cycle`/`review` 구조다. cycle의 trainer에는 기존 store·품질 gate·replay_root·intake_out·camera_profile, recipes에는 명시 연구 recipe를 둔다. requests_dir와 reviews_dir는 새 pipeline 전용 경로, authority.path는 해당 reviews의 `.authority/current.json`, max_age_s는 90 이하이다. review에는 실제 source_proof_files, staging_parent, dataset_name과 필요한 eval_companion_files를 지정한다. 그룹·정답·카메라 수용을 임의로 true로 만들지 않는다.

서비스 템플릿 4개(`rosy-review-bridge.service/.timer`, `rosy-review-pipeline.service/.timer`)를 사용자 systemd에 설치한다. 사용자 manager의 supplementary group에 기존 Store 쓰기 그룹이 포함되어 있어야 한다. 실행 중 primary group을 바꾸면 D-446의 같은 사용자 프로세스 조회가 거절될 수 있으므로 `sg`로 감싸지 않는다. bridge는 승인된 불변 검수 코드에서 짧게 실행하며 GPU 잠금을 잡지 않는다. 학습 owner는 D-446 실행기로 source/environment와 GPU 작업 잠금을 유지한다. 따라서 긴 학습 중에도 현재 결정의 TTL·철회가 갱신된다. 기존 다른 learning-cycle 서비스와 state를 덮어쓰거나 중복 실행하지 않는다.

서비스를 시작하기 전에 `mkdir -p ~/rosy-ml/review-pipeline/cycle-state`로 결과 폴더를 만든다. systemd가 여기에 controller의 stdout을 `summary.json`으로 기록한다. 학습 진행 로그는 journal의 stderr로 남으며 GPU 자원 대기도 실제 summary에 표시한다.

먼저 bridge와 pipeline 서비스를 한 번 실행하고 수신 current.json의 workspace/revision, bridge-state/state.json, cycle-state/state.json의 review_autobuild를 확인한 뒤 타이머를 활성화한다. 사람이 승인한 mask가 없으면 `held / no_approved_masks`이며 학습 요청·GPU 작업을 만들지 않는다. 자료가 준비되면 모든 실제 eval version 및 source pixels를 재검사하고 기존 owner admission으로 처리한다. 학습 화면에는 cycle-state를 Perception 결과로 연결하며 승인 대기 사유를 표시한다.

서명 코드 승인·검수 DB 백업·릴리스 전환·원격 시험·실제 서비스 읽기 증거는 각각 기록한다. 테스트용 승인 fixture를 운영 정답이나 운영 모델로 승격하지 않는다. 새 camera/gate/proof 설정은 기존 원장에 덮어쓰지 않고 명시 새 cycle로 검증한다.

## 학습 화면 수동 제어 (D-745)

운영자가 검수 state의 `learning-control.json`을 마련하면 설치기가 `--learning-control`을 추가한다. 이 private JSON은 다음 다섯 필드만 가진다. 경로는 해당 PC의 링크 없는 절대 경로이며 workspace_id는 실제 작업대의 값을 사용한다.

```json
{
  "schema": "rosy.learning.control/1",
  "workspace_id": "<actual-workspace-id>",
  "service": "rosy-review-pipeline.service",
  "config_path": "/home/rosy/.config/rosy/review-pipeline/pipeline.json",
  "out_path": "/home/rosy/rosy-ml/review-pipeline/cycle-state"
}
```

먼저 기존 pipeline service/timer를 설치하고 daemon-reload한다. 서비스는 템플릿의 단일 서명 ExecStart, `KillMode=control-group`을 사용하며 추가 실행 명령이나 drop-in은 허용하지 않는다. UI는 적재된 unit과 private binding/config 원본을 재확인한다. 설정이 바뀌면 운영자가 명시적으로 다시 연결한다.

Perception 결과로 out_path를 연결하면 시작·중지·재시도 버튼이 나타난다. Ctrl+K에서 같은 이름으로 실행할 수 있다. 시작은 자동 확인을 켜고, 중지는 해당 실행기의 자식 프로세스까지 중지하며, 재시도는 자동 확인을 켜지 않고 한 번 실행한다. 완료·품질 거절·시도 한도 원장은 초기화하지 않는다. 원장 읽기 오류가 있어도 검증된 실행기의 중지는 가능하다. 화면은 실제 서비스 상태와 현재 학습 결과를 다시 읽으며 요청 접수를 완료로 표시하지 않는다.

## Learning SIM 실행 연결

기존 검수 state의 `sim-config.json`을 소유자 전용 일반 파일(0600)로 마련하면 설치기는 대상 앱의 CLI 지원 여부를 확인해 `--sim-config`를 연결한다. 이전 앱으로 복귀하면 지원하지 않는 인자는 제거하고, 지원하는 앱으로 돌아오면 같은 state의 연결을 복원한다. 잘못된 파일 권한이나 링크는 서비스 전환 전에 거절한다.

설정은 기존 `sim_web.LocalRuns`의 정확한 여섯 필드(`workspace_id`, `source_sha`, `source_root`, `binding_file`, `binding_sha256`, `entry_sha256`)를 사용한다. 실제 workspace와 별도로 설치된 clean Git 실행 소스·binding·entry 지문을 결속한다. SDK 실행 소스를 검수 release에 복제하지 않는다. 앱 시작과 독립 운영 조회에서 실제 결속을 검증하며, 페이지 HTTP 200만으로 실행 연결을 수용하지 않는다. 기존 실행의 보고서·단계별 PNG를 조회해 검증하고 신규 실행은 별도로 판단한다.

## 헤드리스 Gazebo 준비 (D-571)

모델 PC는 시뮬레이션의 기본 실행 위치다. 2026-10-09 rootless `--dry-run`에서 `approval=sim` apt 줄은 차이가 없었다(필요한 패키지가 이미 설치됨). 패키지가 빠지면 소유자가 저장소 checkout에서 한 번 실행한다.

```bash
python3 deploy/hosts/common/rosy-host-state install model --dry-run      # root 없이 차이만
sudo python3 deploy/hosts/common/rosy-host-state install model --approve sim
```

네이티브 실행은 `~/rosy-test/runs/sim-*`에서 실행마다 8코어(`CPUQuota=800%`), 6 GB(`MemoryMax`), `nice 10`, 45분으로 제한한다. D-568의 `sim` 하한(잠금·예약을 뺀 여유 코어 6, 8 GB)에 못 미치거나 `~/rosy-jobs/busy`가 있으면 실행기가 이 PC를 고르지 않는다. 실행과 점검 명령은 개발 PC에서 내고, Gazebo는 고른 PC에서만 돈다(D-584). `--host model`은 `ROSY_SIM_HOSTS`나 `private/lab-hosts.json`의 `sim_hosts`에 `=model` 역할이 적혀 있어야 한다.

```bash
python tools/remote/remote_sim.py --check
python tools/remote/remote_sim.py --host model swarm_bench -- --scenario follow --duration 90
```
