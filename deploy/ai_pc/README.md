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
