# AI PC Decision 반복 재생과 watchdog — 2026-10-08

- 범위: D-516 오프라인 AI PC. Laya 0.4.0, PyTorch CPU, `multilingual` checkpoint revision `7b928d828b7b0e022f929d9bd2e44165aa270148`. `/health`는 실제 장치를 `cpu`로 반환했다.
- 재생 도구: `tools/decision_replay.py` SHA-256 `ca0777dc4bb2eff4085fcdbdef0270938c54379055235e26e067c356eb3dcefb`. 합성 `smoke.jsonl` SHA-256 `c67ebce24dd11280d3ad3ee07d6d5c38c3d37c31ec721201aeaa98ebb415994e`를 동일 서버에 5회 재생했다. 각 회 2건 중 1건 일치, 호출 오류 0, 예측 `ESCALATE, ESCALATE`; 각 회 p95는 523.0–538.3ms. 원시 결과는 `X:\DevTemp\rosy-decision-watchdog-20261008\repeat-*.json`에 보관했다.
- GPU: `nvidia-smi -L` exit 9. DKMS `nvidia/580.178.04`가 현재 커널 `7.0.0-34-generic`에 설치돼 있고 Secure Boot가 켜졌지만, NVIDIA 장치 노드와 작동하는 드라이버는 없다. 관리자 권한을 요구하는 드라이버 변경은 하지 않았다.
- watchdog: `ai` 사용자 linger `yes`; `rosy-ai-gpu-watchdog.timer` 활성/활성화, 첫 수동 검사와 1분 뒤 정기 검사 모두 `rosy-ai-gpu-watchdog.service` exit 9 및 journal 오류를 남겼다. `systemd-analyze verify`는 세 유닛에 경고를 내지 않았다.
- 추론 서비스: `rosy-decision-laya.service`는 설치했으나 disabled. 수동 시작 검사에서 GPU preflight가 exit 9로 거부되어 `:8000` listener가 생기지 않았다. 임시 CPU 재생 서버는 시험 후 중지했고 `:8000` listener가 없는 것을 확인했다.
- 저장소 검증: Decision 재생/문서 배치 관련 시험 18 passed, 1 skipped, `known_failures.py` 0 NEW. 생성 색인 갱신 뒤 harness 계약 2 passed, 0 NEW, lint 오류 0(기존 stale-verification 경고 23건).

합성 2건의 반복은 연결 안정성만 보여 준다. 사람 정답 세트, Kev 비교, GPU 지연/공유 부하, VLM, 고정 ModelProfile 승격 및 Fleet/CORE 경로는 아직 수용되지 않았다. GPU 드라이버 복구 후 `/health`의 실제 장치와 고정 revision을 확인하고 GPU 재생을 다시 수행해야 한다.
