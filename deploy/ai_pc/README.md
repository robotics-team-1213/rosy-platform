# AI PC 추론·배포 스모크 서비스

D-516·D-527 범위의 AI PC 추론 호스트용 systemd 사용자 유닛이다. 독립 모델 평가와 승격 증거는 [Model PC](../model_pc/README.md)가 맡는다. 여기서는 승인된 고정 산출물의 적재·GPU·loopback 스모크·watchdog만 확인한다. GPU 타이머는 장치 인식 실패를 journal에 남긴다. Laya 서비스는 loopback 추론을 재시작하지만 GPU 검사 실패 시 시작하지 않는다. Fleet/CORE와 연결하지 않는다.

`ai` 계정에서 이 폴더의 세 유닛을 `~/.config/systemd/user/`에 복사하고 `systemctl --user daemon-reload`를 실행한다. GPU 타이머만 `systemctl --user enable --now rosy-ai-gpu-watchdog.timer`로 켠다. 로그인 종료 후에도 실행하려면 `loginctl show-user ai -p Linger`가 `yes`여야 한다. 실패 기록은 `journalctl --user -u rosy-ai-gpu-watchdog.service`에서 본다.

GPU가 정상이고 Model PC에서 승인된 digest·revision과 최소 비식별 스모크 입력을 확인한 뒤에만 `systemctl --user start rosy-decision-laya.service`로 서버를 켠다. 실제 적재 버전, GPU readback, loopback 응답·지연·timeout과 watchdog을 기록한다. 이 스모크의 일치 수치를 모델 정확도나 승격 증거로 쓰지 않는다. `systemctl --user enable`은 사용하지 않는다. 시험 후 `systemctl --user stop rosy-decision-laya.service`로 종료하고 `ss -ltn`에서 `:8000` listener가 없는지 확인한다. 서비스는 현재 AI PC의 `~/rosy-decision-eval/.venv`를 전제로 하므로 다른 계정/경로에서 쓰기 전에 경로와 모델 revision을 확인한다.

## 신호 요청 제어기 (D-525 rev 4)

`rosy-signal-agent.service`는 Fleet 지도 상황(`GET /api/fleet/traffic`, `GET /api/fleet/guide`)을 0.5 s마다 읽고, 요청(`demand`) 모드인 가상 신호의 입구에 로봇이 기다리면 `POST /api/fleet/traffic/signals/{id}/demand`(ttl 2 s)로 녹색을 **요청만** 한다. 로봇 명령이나 다른 신호 동사는 보내지 않는다. 녹색은 Fleet이 구역이 비었을 때만 켜고, 로봇은 여전히 D-517 통행권으로만 움직인다. 제어기가 5 s 동안 말이 없으면 Fleet이 그 신호를 자동 순환(`cycle`)으로 돌리고 `controller_lost`를 띄운다. 코드는 `operations/fleet/fleet/traffic/signal_agent.py`이고 표준 라이브러리만 쓴다.

1. 현장 `site-users.yaml`에 이 제어기용 이름 있는 운영자 토큰을 하나 만든다(사람 운영자 토큰을 같이 쓰지 않는다).
2. AI PC `ai` 계정에 저장소를 `~/rosy-platform`으로 두고(`git pull`), 토큰을 `~/.config/rosy/signal-agent.token`(권한 600)에, Fleet TLS CA를 `~/.config/rosy/fleet-ca.pem`에 둔다.
3. `~/.config/rosy/signal-agent.env`:

   ```
   FLEET_URL=https://<관제 PC>:<포트>
   FLEET_TOKEN_FILE=/home/ai/.config/rosy/signal-agent.token
   FLEET_CA=/home/ai/.config/rosy/fleet-ca.pem
   ```

4. 손으로 먼저 본다: `cd ~/rosy-platform/operations/fleet && set -a && . ~/.config/rosy/signal-agent.env && set +a && python3 -m fleet.traffic.signal_agent`. 관제 화면 신호 카드에서 운영자가 "AI 요청"을 눌러야 요청이 받아들여진다(그 전에는 409 `SIGNAL_NOT_DEMAND` 경고만 찍힌다).
5. 유닛: `cp rosy-signal-agent.service ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user start rosy-signal-agent.service`. 기록은 `journalctl --user -u rosy-signal-agent.service`. 끄면 5 s 뒤 Fleet이 자동 순환으로 돌아간다.

## 상황 서비스 (D-577, rosy-situation)

`rosy-situation.service`는 Fleet 상태를 읽고 사실·제안만 `ai_observer`로 올린다(로봇 주소·토큰 없음). AI PC 소유자 동의(D-492)는 사용자가 2026-10-10에 주었다. `owner_mode`는 `~/.config/rosy/situation-owner-mode`(`shared`)다.

**알려진 커밋에서만 돌린다.** 서비스는 시작할 때 자기 git 커밋을 읽어 heartbeat의 `build_commit`으로 보낸다. 관제 화면 「연동 상태」와 `GET /api/fleet/ai`의 `status.build_commit`에 보인다. 끝에 `-dirty`가 붙으면 그 PC에서 `operations/situation` 파일이 고쳐진 것이다.

1. 배포할 커밋을 정한다(`origin/main`에 있는 것, 대개 착지한 main).
2. AI PC `ai` 계정에서: `sh ~/rosy-platform/deploy/ai_pc/deploy-situation.sh <커밋>`. 커밋마다 `~/rosy-situation/<sha>`에 분리 worktree를 만들고, `~/rosy-situation/current`를 옮기고, 유닛을 그 커밋 것으로 복사해 다시 띄운다. `~/rosy-platform` 체크아웃(신호 제어기가 씀)은 바꾸지 않는다.
3. 관제 화면 「연동 상태」의 AI PC 버전이 그 sha인지, heartbeat 나이가 6 s 미만인지 본다.
4. 되돌리기: 이전 sha로 2를 다시 한다. 오래된 worktree는 `git -C ~/rosy-platform worktree remove ~/rosy-situation/<sha>`로 지운다.

`~/.config/rosy/situation.env`(`FLEET_URL`, `FLEET_TOKEN_FILE`, `FLEET_CA`)와 토큰 파일은 배포가 건드리지 않는다.

**자동 업데이트 (D-805).** `rosy-situation-autoupdate.timer`(사용자 유닛, 10분마다)가 `ci-result`가 통과한 main을 `~/rosy-situation/releases/<sha12>`에 풀고(`operations/situation`, `contracts/foundation`, `deploy/ai_pc`, 업데이터 자신), 가져오기 확인(smoke) 뒤 `current`를 옮기고 `rosy-situation.service`를 다시 띄운다. 10 s 뒤 active가 아니면 이전 릴리스로 되돌리고 다시 띄운다. 다시 띄우기 전에 `unit_files`(서비스·업데이터 유닛)를 그 릴리스에서 `~/.config/systemd/user/`로 복사하고 `daemon-reload`한다. 그래서 main에서 유닛을 고치면 그대로 따라오고, 되돌리면 이전 유닛도 돌아온다. 업데이터는 OMX 셀과 같은 `deploy/robot/omx/omx_autoupdate.py`(`"kind": "service"`)다. heartbeat의 `build_commit`은 릴리스의 `RELEASE` 파일에서 읽는다. 동결 태그 `ops-update-freeze`가 있으면 관문(`/usr/local/bin/rosy-update-gate`)이 실행을 건너뛴다.

설치(소유자 동의 후, `ai` 계정, 한 번):
1. `cp deploy/ai_pc/situation-autoupdate.json.example ~/.config/rosy/situation-autoupdate.json` 후 `<owner>`를 채운다.
2. 첫 실행은 저장소 사본의 업데이터로: `python3 deploy/robot/omx/omx_autoupdate.py --config ~/.config/rosy/situation-autoupdate.json run`. `current`가 새 릴리스를 가리키게 된다.
3. `rosy-situation.service`, `rosy-situation-autoupdate.{service,timer}`를 `~/.config/systemd/user/`에 복사하고 `systemctl --user daemon-reload && systemctl --user enable --now rosy-situation-autoupdate.timer`.

자동 업데이트로 옮긴 뒤 예전 `~/rosy-situation/<sha>` worktree는 쓰이지 않는다. `git -C <원래 저장소> worktree remove`로 지운다(업데이터는 `releases/`만 정리한다).

타이머가 켜져 있으면 위의 `deploy-situation.sh`로 옮긴 커밋은 다음 실행에서 최신 main으로 돌아간다. 특정 커밋에 묶어 두려면 타이머를 끄고(`systemctl --user disable --now rosy-situation-autoupdate.timer`) 쓴다. 상태: `python3 ~/rosy-situation/current/deploy/robot/omx/omx_autoupdate.py --config ~/.config/rosy/situation-autoupdate.json status`.

## Qwen3-VL 로컬 추론 (D-619)

소유자가 설치·사용을 승인한 AI PC에는 검증한 Ollama 실행 파일을 `~/rosy-models/ollama/dist`에, 같은 `qwen3-vl:8b-instruct` manifest와 해시를 확인한 blobs를 `~/rosy-models/ollama/models`에 둔다. `rosy-ollama.service`를 사용자 유닛으로 설치한다. `127.0.0.1:11434`만 열며 모델 PC의 임시 tunnel을 대체한다. `ollama --version`, `/api/tags`의 digest, `/api/ps`의 GPU 적재와 문맥 길이, 실제 영상 응답·시간을 함께 확인한다. 적재·스모크 성공은 정확도나 주행 수용을 뜻하지 않는다.

기본 환경은 context 8192, Flash Attention, f16 KV cache, 단일 동시 작업·단일 적재 모델·15분 유지다. 선택 `~/.config/rosy/ollama.env`로 문맥 길이를 조정하고 유닛을 재시작한다. 정확도 시험은 같은 프롬프트·영상·모델 digest로 8192/16384와 샘플링을 비교해 관찰 오해석과 10초 deadline을 기록한다. 저정밀 KV cache나 더 큰 문맥을 정확도 개선으로 자동 인정하지 않는다. API request의 options가 환경 기본값을 덮어쓸 수 있으므로 평가 기록에 실제 options도 저장한다.

상황 서비스의 `situation.env`에는 선택 `ROSY_VLM_OPTIONS={"num_ctx":8192,"temperature":0,"seed":42}`를 둘 수 있다. 지원 키는 num_ctx(4096–16384 정수), temperature(0–1), seed(0–2147483647 정수), repeat_penalty(0.8–1.2), top_p(0.1–1), top_k(1–100 정수)다. 잘못된 키·값은 시작 시 거절한다. 기본값은 위 JSON이며 실제 options는 evidence.model_options와 모델 profile의 options 해시에 기록된다. 변경 후 situation 서비스도 재시작한다.

## 헤드리스 Gazebo 준비 (D-571)

AI PC는 다른 사람과 같이 쓴다. 아래 설치는 **소유자가 동의한 뒤 소유자가 직접** 실행한다. 설치하기 전에는 `tools/remote/remote_sim.py`가 이 PC를 `no sim capability`로 건너뛴다. 2026-10-09 rootless `--dry-run` 결과 빠진 패키지는 `ros-jazzy-ros-gz ros-jazzy-gz-ros2-control ros-jazzy-navigation2 ros-jazzy-nav2-bringup ros-jazzy-slam-toolbox ros-jazzy-realtime-tools ros-jazzy-joint-state-publisher`이다.

```bash
python3 deploy/hosts/common/rosy-host-state install ai --dry-run         # root 없이 차이만
sudo python3 deploy/hosts/common/rosy-host-state install ai --approve sim
```

`--approve sim`은 apt 패키지만 더한다. D-530의 다른 승인 줄(sshd, sudoers, 워치독)은 이 명령으로 바뀌지 않지만, 같은 명령이 `safe` 줄(새벽 재부팅 유닛 등)과 `report` 줄도 적용하므로 소유자가 `--dry-run` 출력을 먼저 확인한다. apt는 빠진 패키지만 `--no-upgrade --no-remove`로 설치하므로 이미 있는 패키지를 올리거나 지우지 않는다. CORE pip 의존성 설치, colcon 빌드, 벤치는 4코어, 4 GB, `nice 10`의 사용자 scope 안에서 돈다. 커밋 전송, 출력 가져오기, 정리는 scope 밖에서 `nice 15`와 idle I/O로 돈다. D-568의 `sim` 하한(잠금·예약을 뺀 여유 코어 6, 8 GB)에 못 미치거나 `~/rosy-jobs/busy`가 있으면 이 PC를 고르지 않는다. 소유자는 `echo "$(( $(date +%s) + 7200 )) $USER $$" > ~/rosy-jobs/busy`(만료 시각, 소유자, pid)로 언제든 막을 수 있다. 만료가 지난 표시는 무시하고, 만료 없이 `touch`만 한 표시는 이번 부팅 동안만 막는다. 실행기는 자기 scope(`rosy-sim-*.scope`) 밖의 프로세스를 멈추지 않는다.
