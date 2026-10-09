# AI PC 추론·배포 스모크 서비스

D-516·D-527 범위의 AI PC 추론 호스트용 systemd 사용자 유닛이다. 독립 모델 평가와 승격 증거는 [Model PC](../model_pc/README.md)가 맡는다. 여기서는 승인된 고정 산출물의 적재·GPU·loopback 스모크·watchdog만 확인한다. GPU 타이머는 장치 인식 실패를 journal에 남긴다. Laya 서비스는 loopback 추론을 재시작하지만 GPU 검사 실패 시 시작하지 않는다. Fleet/CORE와 연결하지 않는다.

`ai` 계정에서 이 폴더의 세 유닛을 `~/.config/systemd/user/`에 복사하고 `systemctl --user daemon-reload`를 실행한다. GPU 타이머만 `systemctl --user enable --now rosy-ai-gpu-watchdog.timer`로 켠다. 로그인 종료 후에도 실행하려면 `loginctl show-user ai -p Linger`가 `yes`여야 한다. 실패 기록은 `journalctl --user -u rosy-ai-gpu-watchdog.service`에서 본다.

GPU가 정상이고 Model PC에서 승인된 digest·revision과 최소 비식별 스모크 입력을 확인한 뒤에만 `systemctl --user start rosy-decision-laya.service`로 서버를 켠다. 실제 적재 버전, GPU readback, loopback 응답·지연·timeout과 watchdog을 기록한다. 이 스모크의 일치 수치를 모델 정확도나 승격 증거로 쓰지 않는다. `systemctl --user enable`은 사용하지 않는다. 시험 후 `systemctl --user stop rosy-decision-laya.service`로 종료하고 `ss -ltn`에서 `:8000` listener가 없는지 확인한다. 서비스는 현재 AI PC의 `~/rosy-decision-eval/.venv`를 전제로 하므로 다른 계정/경로에서 쓰기 전에 경로와 모델 revision을 확인한다.

## 헤드리스 Gazebo 준비 (D-571)

AI PC는 다른 사람과 같이 쓴다. 아래 설치는 **소유자가 동의한 뒤 소유자가 직접** 실행한다. 설치하기 전에는 `tools/remote/remote_sim.py`가 이 PC를 "준비 안 됨"으로 건너뛴다. 2026-10-09 rootless `--dry-run` 결과 빠진 패키지는 `ros-jazzy-ros-gz ros-jazzy-gz-ros2-control ros-jazzy-navigation2 ros-jazzy-nav2-bringup ros-jazzy-slam-toolbox ros-jazzy-realtime-tools ros-jazzy-joint-state-publisher`이다.

```bash
python3 deploy/hosts/common/rosy-host-state install ai --dry-run         # root 없이 차이만
sudo python3 deploy/hosts/common/rosy-host-state install ai --approve sim
```

`--approve sim`은 apt 패키지만 더한다. D-530의 다른 승인 줄(sshd, sudoers, 워치독)은 이 명령으로 바뀌지 않지만, 같은 명령이 `safe` 줄(새벽 재부팅 유닛 등)과 `report` 줄도 적용하므로 소유자가 `--dry-run` 출력을 먼저 확인한다. 실행은 4코어, 4 GB, `nice 10`의 사용자 scope 안에서만 돌고, 남은 메모리 4 GB 미만이거나 코어당 부하 0.9 초과면 이 PC를 고르지 않는다. 같은 계정의 다른 사람 `gz sim`은 점수만 낮추고, 실행기는 자기 scope(`rosy-sim-*.scope`) 밖의 프로세스를 멈추지 않는다.
