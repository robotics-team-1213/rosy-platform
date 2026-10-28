# SmolVLA 미세 조정 GPU 메모리 (2026-10-27)

**위치:** AI PC (RTX 5080 Laptop 16GB) · **관련:** D-866 §4와 2026-10-27 보완(학습 전 VRAM 확인)

## 주장과 한계

- 기본 설정(`freeze_vision_encoder`, `train_expert_only`, chunk 50)으로 OMX 모양 배치를 학습할 때 한 걸음(순전파·역전파·AdamW)의 최대 할당량은 배치 8에서 2.96GB, 16에서 4.63GB다.
- 측정 시각에 AI PC GPU는 이미 10.2GB를 쓰고 있었다(ollama 8.2GB, 다른 사람의 SAM 벤치 2.1GB). 남은 약 6GB 안에서는 **배치 16까지만** 들어간다. 배치 32는 5GB 상한을 넘었다.
- 배치 32·64는 재지 않았다. 8→16 증가분(배치 8당 1.67GB)으로 늘리면 32는 약 8GB, 64는 약 15GB다. 추정이며, 64는 ollama가 GPU를 비워야 들어간다.
- 데이터 적재기·정규화·영상 디코딩은 빠졌다. 실제 `lerobot-train`은 이보다 조금 더 쓴다. 학습 품질과 속도는 판단하지 않는다.

## 방법

- 스크립트: [`evidence/smolvla_train_mem.py`](evidence/smolvla_train_mem.py). `lerobot/smolvla_base`(LeRobot 0.4.4, torch 2.7.1+cu128, 시험 PC의 `policy-latency-gpu` 환경)를 OMX 특징(상태 6, 행동 6, 카메라 `top`·`front` 480×640)으로 불러온다. 영상은 모델 안에서 512×512로 바뀌므로 입력 크기는 메모리에 거의 영향이 없다.
- 무작위 텐서 배치와 정책 자신의 tokenizer로 만든 과제 문장을 쓴다. 배치마다 3걸음을 돌려 AdamW 상태가 잡힌 뒤의 최대값을 `torch.cuda.max_memory_allocated`로 읽는다.
- `torch.cuda.set_per_process_memory_fraction`으로 이 프로세스를 5GB로 묶어 메모리 부족이 다른 프로세스에 번지지 않게 했다. `tools/remote/hold_gpu.sh 4 8`로 실행해 그동안 그 PC의 시뮬레이터 자리를 막았다.

```
HF_HUB_OFFLINE=1 tools/remote/hold_gpu.sh 4 8 <policy-latency-gpu>/bin/python smolvla_train_mem.py <smolvla_base snapshot> 5 8,16,32,64
```

## 결과

| 배치 | 최대 할당 GB | 최대 예약 GB | 걸음당 초 |
|---|---|---|---|
| 8 | 2.96 | 3.01 | 1.49 (첫 걸음 포함) |
| 16 | 4.63 | 4.69 | 0.44 |
| 32 | 5GB 상한 초과 | | |

가중치만 0.86GB, 학습 파라미터 9,988만 개.

## 다음

- AI PC에서 ollama와 함께 학습하면 배치 16 이하로 하거나 gradient accumulation을 쓴다. 배치 32 이상은 모델 PC(측정 시 GPU 16MB 사용)에서 하거나 ollama를 내린 시간에 한다. 그 PC에는 아직 `smolvla_base`와 GPU LeRobot 환경이 없다.
