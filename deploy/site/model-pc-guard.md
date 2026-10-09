# 모델 PC 멈춤 대비

2026-10-07 02:13 모델 PC(OMEN)가 메모리 부족으로 멈췄다. 사람이 전원을 다시 켤 때까지 17시간 꺼져 있었다.
- 로그에는 NVIDIA `NV_ERR_NO_MEMORY`, ollama "host memory pressure", 끝없는 i915 `Purging GPU memory`가 남았다.
- swap 32 GiB는 ZFS 볼륨(`rpool/swap2`)이다. 메모리가 바닥나면 ZFS도 swap을 쓰려고 메모리가 필요해서 시스템 전체가 멈출 수 있다. swap 크기를 키워도 이 문제는 풀리지 않는다.

대비는 세 겹이다.

| 겹 | 하는 일 | 어디 |
|---|---|---|
| swap 이전 | ZFS swap을 끄고 zram(압축 RAM)을 RAM 크기로 키운다. 4 GiB 암호화 swap 파티션은 남긴다 | 모델 PC |
| 커널 멈춤 | 하드웨어 워치독(`iTCO_wdt`)을 systemd가 30초마다 확인한다. 커널이 멈추면 보드가 재부팅한다. 커널이 lockup을 감지해도 10초 뒤 재부팅한다 | 모델 PC |
| 반쯤 멈춤 | 관제 PC 가드(D-530)가 10분마다 SSH로 메모리·부하·감시 유닛을 묻는다. 30분 연속 나쁘면 재부팅시킨다. 새벽 예약 재부팅(06:03–06:05) 앞뒤와 부팅 1시간 안은 건드리지 않는다 | 관제 PC |

커널이 완전히 멈추면 SSH도 응답하지 않는다. 그래서 관제 PC 점검은 "연결 안 됨"을 기록만 하고, 그 경우는 워치독이 맡는다.

## 설치 (한 번, sudo 비밀번호를 아는 사람)

관제 PC 점검은 D-530의 일반 가드(`rosy-host-guard`)가 맡는다. 같은 가드가 AI PC와 로봇도 본다.

1. 관제 PC에서 가드를 설치하고 공개키를 받는다. `/etc/rosy/host-guard/hosts.conf`에 대상을 적는다(`host-guard.conf.example`).
   ```bash
   sudo deploy/site/install-host-guard.sh
   ```
2. 모델 PC에서 대비를 설치하고 그 키를 등록한다. 키는 `rosy-host-guard-remote`(`health`, `restart <유닛>`, `reboot`)만 실행할 수 있고, 다시 시작과 재부팅은 D-524 도우미 `rosy-host-control`이 한다(`rosy-host-state install model --approve ...`로 설치).
   ```bash
   sudo deploy/site/install-model-pc-guard.sh --site-key "ssh-ed25519 AAAA... rosy-host-guard"
   ```
   AI PC는 `sudo deploy/hosts/common/install-guard-remote.sh --site-key "..." --unit pinky-backend.service ...`이다(소유자 동의 뒤).
3. 관제 PC에서 1번을 다시 실행해 연결을 확인하고, `sudo python3 deploy/hosts/common/rosy-host-state install site`로 타이머를 켠다.

무엇이 바뀌는지는 모든 스크립트에서 `--dry-run`으로 먼저 볼 수 있다(sudo 불필요).

## 확인

- 모델 PC: `swapon --show`(zvol 없음), `ls /dev/watchdog*`, `sysctl kernel.panic`(10), `sudo -l -U rosy`(reboot 한 줄).
- 관제 PC: `systemctl list-timers rosy-host-guard.timer`, `journalctl -t rosy-host-guard`, `/var/lib/rosy-host-guard/status.json`, `actions.jsonl`.

시험: `test/test_host_guard.py`(가짜 ssh로 정상, 나쁨 3회 재부팅, 멈춘 유닛 재시작 뒤 재부팅, 부하, 막 부팅, 연결 안 됨, 새벽 창, 강제 명령 거절).
