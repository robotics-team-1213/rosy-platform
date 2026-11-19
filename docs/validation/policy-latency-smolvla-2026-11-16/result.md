# OMX Two-Arm Fine-Tuned SmolVLA Policy Runner Latency Benchmark (2026-11-16)

- Reference ADR: [D-854](../../adr/D-854-omx-policy-runner-and-action-space.md)
- Checkpoint: `/home/ai/rosy-scratch/smolvla-grasp-v24/root/two_arm_rounds/20261116T032207-caf27aaa/train/checkpoints/001500/pretrained_model`
- Checkpoint digest (`checkpoint_digest`): `cd40e572c1f8a9a582a397f8871baff092ab41609be74f99522724e1735af7fa`
- `model.safetensors` sha256: `d0f23a6fdeca0a3460a2090bbee571ebf556d1de9971182749572be87f45af39`
- Hardware & runtime: `NVIDIA GeForce RTX 5080 Laptop GPU` (AI PC), `torch 2.7.1+cu128`, `lerobot 0.4.4`, `use_amp=True`
- Load condition: measured concurrently with live `smolvla` training on the same GPU (~98% GPU utilization, ~8.4 / 16.3 GiB VRAM used)
- Input shape: 12 joints (`lerobot_norm_v1`), 4 cameras (`top`, `side`, `a_wrist`, `b_wrist` at `240x320`), `SyntheticTarget`, `--warmup 5 --steps 25`

## Results (`python -m rosy.integrations.robots.omx.policy_runner`)

| Run | `num_steps` | `n_action_steps` | `use_amp` | `infer` p50 (ms) | `infer` mean (ms) | `infer` p95 (ms) | `preprocess` p50 (ms) | `end_to_end` p50 (ms) | `end_to_end` mean (ms) | `end_to_end` p95 (ms) |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Default (`n_action_steps=1`) | 10 | 1 | `true` | 339.25 | 331.06 | 369.56 | 84.52 | 428.79 | 435.25 | 524.71 |
| Accelerated (`--amp --flow-steps 5 --n-action-steps 8`) | 5 | 8 | `true` | 5.64 | 36.13 | 267.87 | 151.54 | 162.66 | 183.13 | 376.82 |

## Observations

1. **Action chunking + flow-step reduction drops neural-net inference ~9.2x mean (331.06 ms -> 36.13 ms, 60.1x p50).** When popping cached actions from the 8-step queue (`n_action_steps=8`), `select_action()` returns in single-digit milliseconds (`p50=5.64 ms`), only running diffusion steps (`num_steps=5`, `p95=267.87 ms`) at chunk boundaries.
2. **End-to-end drops 2.38x mean (435.25 ms -> 183.13 ms), leaving `preprocess` as the next bottleneck (~85–152 ms on synthetic frames).** In `policy_runner.LeRobotAdapter.preprocess()`, image normalization/tensor conversion and tokenization still execute every step even while popping from an already-computed action chunk.
3. **Fine-tuned checkpoints benefit directly from `--amp`.** Unlike `smolvla_base` (which loaded almost entirely in bf16), the fine-tuned `001500` checkpoint kept `148,811,856` fp32 parameters alongside `301,234,320` bf16 parameters (`use_amp=true` in `config.json`), so CUDA autocast reduces heavy linear/attention cost during inference as well as training.
