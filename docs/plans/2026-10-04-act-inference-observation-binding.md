# ACT Inference Observation Binding Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 실제 ACT가 소비한 고정 모델/정규화/RGB/joint 관측을 행동 후보와 연결하고, queued 행동의 과거 관측을 보존한다.

**Architecture:** 학습 framework는 `learning/training/omx`에만 둔다. 추론기는 PolicyArtifact의 고정 revision과 실제 bytes를 검사해 메모리에 snapshot하고, 인접 호출의 ACT chunk를 소비한 최초 관측/생성 시각과 함께 반환한다. owner·승격·ROS 권한은 생성하지 않는다.

**Tech Stack:** Python 3.12, pinned LeRobot 0.4.4, CPU PyTorch, safetensors byte loader, 기존 stdlib 학습 계약.

---

## Task 1: 관측과 큐 provenance 회귀

Create `learning/training/omx/test/test_act_inference.py`.
불변 RGB bytes, image SHA·joint 순서·calibration 대조, 틀린 pin·변조 거절,
queued action이 새 frame/생성 시각을 주장하지 않는 것, lease/episode/reset에서 큐가 사라지는 것을 먼저 시험한다.
framework가 없는 host에서는 fake numerical backend를 사용하며 실제 bytes 검사와 입력 binding은 실행한다.
Run `python -B -m pytest learning/training/omx/test/test_act_inference.py -q -p no:cacheprovider --basetemp X:/DevTemp/act-inference-red`.
Expected initial failure: 새 모듈 없음.

## Task 2: 고정 bytes와 실제 ACT 추론

Create `learning/training/omx/act_inference.py`.
검증 후 mutable 경로를 다시 읽는 `from_pretrained` 대신 immutable config/weight bytes로 CPU 모델을 구성한다.
다운로드 가능한 pretrained backbone/path와 temporal ensemble는 지원하지 않는다.
모델 shape/feature와 artifact·정규화를 대조하고 예측을 clamp하지 않는다.
출력은 기존 OwnerPolicySession 후보 필드로 변환 가능한 local Python 데이터이며 public wire가 아니다.
ACT의 n_action_steps와 큐 동작을 유지한다. 오래된 행동을 새 관측과 연결하지 않으며,
owner가 sequence/age를 거절할 수 있도록 source provenance를 그대로 반환한다.
reset은 추론 state만 지우고 owner HOLD/StopFence를 해제하지 않는다.

## Task 3: 실제 보존 평가 replay와 독립 검증

Create `learning/training/omx/act_inference_replay.py`와 native tests.
실제 pinned PolicyArtifact 및 원래 LeRobot 평가 reader를 읽어 모든 평가 프레임에 추론한다.
출력/원본 관측/생성 시각/queue index/RGB SHA와 latency를 새 X artifact로 보존한다.
기존 queued offline metrics를 재현해 모델 소비가 같은지 확인한다. 이미 거절된 연구 모델을 승격하지 않는다.
호스트 시각은 replay 입력 수신의 monotonic이고 원래 capture/state 시각은 별도 보존한다.
이 replay는 independent SIM task나 actual owner dispatch를 대신하지 않는다.

Run native `X:/DevTemp/rosy-omx-lerobot-044/Scripts/python.exe -B -m pytest learning/training/omx/test/ -q -p no:cacheprovider --basetemp X:/DevTemp/act-inference-native`.
영향 범위 tests/문서 guards와 독립 리뷰를 실시하고 `docs/validation/`와 기존 보고서를 갱신한다.

## 후속 실행 공백

trusted issuer·capture/scheduler·ROS owner composition, 독립 SIM 과제, authentic receipt/Fleet,
Pinky owner·rollback stop readback·DEVICE/FIELD, 라벨 검수 및 새 객체/신호 모델은 남아 있다.
현재 정책의 config는 4행동 chunk를 100ms 주기로 내고 관측 budget은 50ms이다.
큐의 과거 관측을 위장하는 대신 실제 owner 거절을 유지한다. 주기/queue 구조 변경은
새 config/revision/평가 증거를 요구하며 기존 연구 artifact를 덮어쓰지 않는다.

## Task 4: 고정 조건의 관측당 1행동 비교

`act_job.run(..., n_action_steps=4)` 기본값은 유지하고 1..4만 명시 허용한다.
새 CLI `--n-action-steps 1`로 원래 train5/eval1 Episode, seed42751, 40steps,
chunk_size4와 네트워크/정규화를 고정한 새 학습 job을 X에 실행한다.
평가 후 조정 없이 variant 1을 비교 대상으로 사전에 고정한다.
새 산출물은 기존 artifact를 덮어쓰지 않고 새 config·평가·canonical revision을 보존한다.
그 variant도 pinned replay/registry 연구 판정을 실행하며 품질 거절을 감추지 않는다.
