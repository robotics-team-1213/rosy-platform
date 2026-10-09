# AI PC 추론·배포 스모크 서비스

D-516·D-527 범위의 AI PC 추론 호스트용 systemd 사용자 유닛이다. 독립 모델 평가와 승격 증거는 [Model PC](../model_pc/README.md)가 맡는다. 여기서는 승인된 고정 산출물의 적재·GPU·loopback 스모크·watchdog만 확인한다. GPU 타이머는 장치 인식 실패를 journal에 남긴다. Laya 서비스는 loopback 추론을 재시작하지만 GPU 검사 실패 시 시작하지 않는다. Fleet/CORE와 연결하지 않는다.

`ai` 계정에서 이 폴더의 세 유닛을 `~/.config/systemd/user/`에 복사하고 `systemctl --user daemon-reload`를 실행한다. GPU 타이머만 `systemctl --user enable --now rosy-ai-gpu-watchdog.timer`로 켠다. 로그인 종료 후에도 실행하려면 `loginctl show-user ai -p Linger`가 `yes`여야 한다. 실패 기록은 `journalctl --user -u rosy-ai-gpu-watchdog.service`에서 본다.

GPU가 정상이고 Model PC에서 승인된 digest·revision과 최소 비식별 스모크 입력을 확인한 뒤에만 `systemctl --user start rosy-decision-laya.service`로 서버를 켠다. 실제 적재 버전, GPU readback, loopback 응답·지연·timeout과 watchdog을 기록한다. 이 스모크의 일치 수치를 모델 정확도나 승격 증거로 쓰지 않는다. `systemctl --user enable`은 사용하지 않는다. 시험 후 `systemctl --user stop rosy-decision-laya.service`로 종료하고 `ss -ltn`에서 `:8000` listener가 없는지 확인한다. 서비스는 현재 AI PC의 `~/rosy-decision-eval/.venv`를 전제로 하므로 다른 계정/경로에서 쓰기 전에 경로와 모델 revision을 확인한다.
