# AI PC 오프라인 평가 서비스

D-516 범위의 평가 호스트용 systemd 사용자 유닛이다. GPU 타이머는 장치 인식 실패를 journal에 남긴다. Laya 서비스는 loopback 추론을 재시작하지만 GPU 검사 실패 시 시작하지 않는다. Fleet/CORE와 연결하지 않는다.

`ai` 계정에서 이 폴더의 세 유닛을 `~/.config/systemd/user/`에 복사하고 `systemctl --user daemon-reload`를 실행한다. GPU 타이머만 `systemctl --user enable --now rosy-ai-gpu-watchdog.timer`로 켠다. 로그인 종료 후에도 실행하려면 `loginctl show-user ai -p Linger`가 `yes`여야 한다. 실패 기록은 `journalctl --user -u rosy-ai-gpu-watchdog.service`에서 본다.

GPU가 정상이고 고정 모델 버전과 재생 입력을 확인한 별도 평가 세션에서만 `systemctl --user start rosy-decision-laya.service`로 서버를 켠다. `systemctl --user enable`은 사용하지 않는다. 시험 후 `systemctl --user stop rosy-decision-laya.service`로 종료하고 `ss -ltn`에서 `:8000` listener가 없는지 확인한다. 서비스는 현재 AI PC의 `~/rosy-decision-eval/.venv`를 전제로 하므로 다른 계정/경로에서 쓰기 전에 경로와 모델 revision을 확인한다.
