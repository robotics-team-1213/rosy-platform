# Decision 재생 파이프라인 재검증 — 2026-10-08

## 범위와 실행물

- 기준 코드: `9ae782908` (`tools/decision_replay.py`, `test/test_decision_replay.py`). 재생 도구 SHA-256: `fb5e2fcf6f4c62a6a1a7478901df6e11722a86596f2b81bfaa470cd3bf408b49`.
- 입력: AI PC의 기존 **합성** `smoke.jsonl` 2건. SHA-256: `c67ebce24dd11280d3ad3ee07d6d5c38c3d37c31ec721201aeaa98ebb415994e`. 사람 라벨 평가 세트가 아니다.
- 호스트: AI PC, Python 3.12.3, Laya 0.4.0, PyTorch 2.14.1+cpu. 모델 서버는 `127.0.0.1`에만 묶고 시험 후 종료했다. 이번 실행에서 모델 checkpoint revision은 다시 확인하지 못했다.
- 입력 JSONL과 원시 결과는 공개 저장소에 넣지 않았다. 비공개 일회성 결과는 `X:\DevTemp\rosy-decision-replay-v2-20261008\ai-pc-laya-smoke.json`에 있다(SHA-256 `66a4964f91938a0fc5cf7aceafaf2758f2d09f521ab98eb036a73a655d885e30`).

## 관측

| 검사 | 결과 | 판정 범위 |
| --- | --- | --- |
| 전체 JSONL 선검증 | 뒤 행의 `expected`가 선택지 밖이면 서버 호출 0건으로 거부. 로컬 가짜 서버 시험에서 수정 전 첫 행 호출을 재현 | 부분 입력 호출 방지 |
| 세트 동일성 | 결과 JSON에 원본 입력 바이트의 `dataset_sha256` 기록 | Laya/Kev 등 동일 입력 비교 시 사용할 식별자 |
| AI PC Laya CPU 연결 | 2건 중 1건 기대값과 일치, 호출 오류 0건, p95 570.9ms | 합성 연결 시험만; 정확도·GPU 지연 아님 |
| 서버 중단 | `predicted=null`, `URLError` 2건, 성공 예측 0건. 수정 전 CLI 종료 코드 0을 재현; 수정 후 같은 입력·서버 부재에서 종료 코드 1, 결과 JSON은 생성 | 오류를 성공 실행으로 보고하지 않음 |
| 로컬 호스트 시험 | `test/test_decision_replay.py` 3 passed; `known_failures.py` 0 new | 도구 계약만 확인 |

정상 Laya CPU 호출에는 CLI 종료 코드 0을 확인했다. 서버 중단 후 `:8000` listener가 없는 것도 확인했다. Laya CPU 연결 때 전송한 스크립트는 최종 CLI 종료 코드 수정보다 한 단계 앞선 SHA-256 `007411e9654e8a0a1616c3bf06106a208a88d552f0d7019e354129ea18482cb4`였고, 선검증·세트 해시 로직은 동일하다. 최종 스크립트의 서버 부재 종료 코드 1은 AI PC에서 확인했다.

## 남은 관문

- AI PC는 이번 점검에서 GPU 장치는 PCI에 보이지만 `/dev/nvidia*`가 없고 `nvidia-smi`가 드라이버와 통신하지 못했다. 커널은 `7.0.0-34-generic`, NVIDIA DKMS `580.178.04`는 설치 상태이며 Secure Boot가 켜져 있다. 원인은 확정하지 않았고 드라이버·부팅 설정은 변경하지 않았다. GPU 지연과 Qwen3-VL 동시 사용은 측정하지 못했다.
- Kev는 이 실행에서 설치·호출하지 않았다. 사람 정답 세트와 모델 revision을 고정한 뒤 동일 세트로 따로 비교해야 한다.
- 모델 PC의 `ModelProfile` 승격·AI PC 적재 readback, 현장 Fleet/VLM adapter, CORE 재검사, 로봇 동작은 이 시험 경로에 없다. [D-516](../../adr/D-516-offline-decision-model-replay-boundary.md)과 [파이프라인 설계](../../plans/2026-10-08-decision-model-pipeline-design.md)의 후속 관문으로 남는다.
