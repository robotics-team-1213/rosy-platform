## 2026-11-20 · uncommitted · feat(omx): observer session handoff for H4 (observer_handoff.py)

- 변경: `rosy-omx-observer@<arm>` 실행 중 `session.lock` 미양보 문제(H4) 해결을 위해 `observer_handoff.py`와 `observer_handoff_io.py`를 추가해 잠금·arm lease 획득, observer 정지 및 포트 비점유 확인, `_lead` 리더(`PR_SET_PDEATHSIG=SIGTERM`) 기반 세션 실행 및 종료 후 재시작을 처리하고 `chunk_runner`가 `--joint-topic`/`snapshot_live`로 관측 스냅샷을 유지하도록 했다. `observation-bridge`·`arm-status` 서비스는 `Restart=on-failure`로 전환했으며 WINNAKEN 리뷰 3건(시그널 SIGHUP 정렬·잔여 프로세스 HOLD·사전 `--arm`/`--config` 포트 대조)을 반영했다.
- 증거: `test/test_omx_observer_handoff.py` 단위 시험 및 원격 pytest, `rosy_harness.py lint` 통과
- gate 변화: 없음 (`cell_arm_lease.py`, `chunk_runner.py`, `chunk_runner_interrupt.py` 안전 경로 `Safety-Review:` 필요)
- 결정: H4
- 교훈: none
