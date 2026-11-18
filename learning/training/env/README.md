# 학습 GPU 환경 (SmolVLA + ACT)

모델 PC 등 GPU 호스트에 모방 학습 환경을 한 번에 만들고, 만들어진 환경이 실제로 끝까지 도는지 증명한다.
로봇·ROS 이미지에는 설치하지 않는다(`learning/AGENTS.md`).

## 파일

| 파일 | 역할 |
|------|------|
| `requirements-policy-gpu.txt` | 모델 PC 작동 환경(`~/rosy-test/venvs/policy-gpu`, 2026-11-19)의 `uv pip freeze` 원본. LeRobot 0.4.4, torch 2.7.1+cu128, transformers 4.57.6. torch는 cu128 인덱스에서 받는다. |
| `provision_policy_gpu.sh [경로] [--verify-only]` | 새 경로(기본 `~/.local/share/rosy-learning/venv-policy-gpu`)에 venv를 만들고(uv, 없으면 `python -m venv`) 핀을 설치한 뒤 torch CUDA, LeRobot ACT·SmolVLA import, transformers를 검사해 JSON 영수증을 출력한다. 같은 핀이면 재설치하지 않고, 기존 환경은 지우지 않으며, venv가 아닌 비어 있지 않은 폴더는 거절한다. GPU가 없으면 경고(`ROSY_REQUIRE_CUDA=1`이면 실패). |
| `bootstrap_model_pc.sh [--check] [--venv 경로]` | 새 모델 PC용 한 명령. nvidia-smi·python3.12·uv·linger·디스크 여유(기본 15 GB) 점검 후 provision을 실행하고 사람이 할 일을 출력한다. `--check`는 보고만 하고 아무것도 설치하지 않는다. |
| `../omx/il_proof.py` | 합성 데이터로 수집 → prepare → 합성 결정 → 분할 → ACT 학습 → 독립 재적재 평가 → (선택) SmolVLA → 등록 dry-run → HF 번들 준비(업로드 없음)까지 돌고 `proof-receipt.json`을 쓴다. |

## 순서

1. `bash learning/training/env/bootstrap_model_pc.sh --check` : 점검만.
2. `bash learning/training/env/bootstrap_model_pc.sh` : 환경 생성 + 검증.
3. 만든 venv의 python으로 증명 실행:
   `<venv>/bin/python learning/training/omx/il_proof.py --out <새 폴더> --device cuda --smolvla`
   (SmolVLA는 HF 캐시의 `lerobot/smolvla_base`와 `HuggingFaceTB/SmolVLM2-500M-Video-Instruct`를 쓰며 내려받지 않는다. 없으면 `--smolvla-base`, `--smolvla-vlm-source`로 경로를 준다.)

## 증명이 말하는 것

영수증은 `"synthetic": true`, `"evidence_of": "environment and wiring only"`다. 환경과 배선이 돈다는 증거일 뿐, 정책 성능·실물 성공·승격·업로드는 아니다. 결정 파일의 reviewer는 `synthetic-proof`이고 사람 검수로 위장하지 않는다.

## 사람만 할 수 있는 일

- 서명 공개키로 `deploy/site/install-model-code.sh` 실행(모델 코드 설치).
- 팀 HF 토큰을 `~/.config/rosy/hf-team-token`에 두고 `chmod 600`. 업로드는 항상 `--token-file`로만 하며 이 스크립트들은 업로드하지 않는다.
- 실물 시연(리더 팔) 수집.
- `sudo loginctl enable-linger <user>`(linger가 꺼져 있을 때).
