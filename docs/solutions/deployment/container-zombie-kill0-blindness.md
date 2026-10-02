---
module: deploy
tags: [containers, signals, zombie, ci, bash]
problem_type: bug
---

# 컨테이너에서 `kill -0`은 좀비를 산 것으로 본다

## 문제

2026-10-02 CI(컨테이너 러너)에서 `test_jpeg_relay` 3건과 `test_rosy_auto_update`의
프로세스 그룹 시험이 "did not exit"로 적색. 윈도 호스트에서는 같은 시험이
skip되거나 통과해 원인이 안 보였다.

## 원인

`kill -0 <pid>`는 **좀비(부모가 회수하지 않은 죽은 프로세스)** 에도 성공한다.
컨테이너의 PID 1이 고아를 회수(reap)하지 않으면, SIGTERM·SIGKILL 후에도
`kill -0`이 계속 성공해 "종료 안 함"으로 판정한다. WSL·실기(init/systemd)는
고아를 회수하므로 재현되지 않는다. 실증(WSL): 부모가 회수 전인 자식을 KILL한
뒤 `kill -0`=성공, `/proc/<pid>/stat` 상태=`Z`.

## 해결

산 판정은 상태 문자까지 본다 — bash(`rec_compact.sh`의 `alive()`)와
시험 헬퍼(`test_rosy_auto_update.py`의 `_alive()`) 모두:

```bash
alive() {
  kill -0 "$1" 2>/dev/null || return 1
  [ "$(_proc_state "$1")" != "Z" ]   # /proc/<pid>/stat 의 마지막 ") " 뒤 문자
}
```

같은 회차의 `test_image_layer_sync` 적색은 다른 원인: 모드 드리프트 시험이
`0o644`로 전제를 걸어 실제 Linux 체크아웃(git 100644)에서 드리프트가 사라졌다.
기저 모드 무관한 `0o600`으로 독립시켰다.

## 교훈

- 리눅 전용·컨테이너 의존 시험은 윈도 호스트의 "통과"가 증거가 아니다(skip 포함).
- DrvFS(/mnt/f) 체크아웃은 모드가 777로 뭉개져 모드 시험의 신뢰 검증용이 될 수 없다 —
  ext4로 클론해 검증한다.
