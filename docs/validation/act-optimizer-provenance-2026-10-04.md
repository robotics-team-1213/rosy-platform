# ACT optimizer provenance 수정과 동일 결과 대조

2026-10-04, 기준 checkout `178f99b9a`, LeRobot 0.4.4 / Torch 2.7.1 CPU.
수정 trainer SHA-256: `5290d2127770c8db29e40c9eacc0329fa650539509b3d313862f59df9768b7a0`.

## 문제와 수정

기존 custom trainer는 모든 policy parameter에 하나의 AdamW group을 적용하며
lr=0.001, weight_decay=0.0001로 학습했다. 저장 ACTConfig에는 사용하지 않은
기본 lr=0.00001이 남아 있어 config만 읽으면 실제 학습 설정을 오해할 수 있었다.

새 실행은 ACTConfig의 optimizer_lr와 optimizer_lr_backbone을 모두 0.001,
optimizer_weight_decay를 0.0001로 명시하고 실제 optimizer가 이 config 값을 사용한다.
backbone에 별도 group을 만든 것은 아니다. offline-report는 실제 parameter_groups의
lr/weight_decay/betas/eps 및 실행 옵션, 전체 parameter 단일 group, clip norm 1.0을 기록한다.
과거의 config/가중치/평가/거절 이력은 수정하지 않았다.

## 실제 대조 실행

`X:/DevTemp/rosy-learning-audit-20261004/run_act_optimizer_control.py`는 실행 전에
새 trainer bytes와 실험 설정, 원래 reader 입력 135개의 hash를 보존했다.
기존 5 train / 1 고정 validation Episode, seed42751, 40 steps, n_action_steps=1을 사용했다.
산출물: `omx-act-optimizer-control-v1`, 검증 근거: `act-optimizer-provenance-v1`.

- 실행 handle67535 terminal **exit0**, elapsed238.438s. Torchvision deprecation warning은 있었으나 traceback은 없다.
- 저장 config와 실제 보고서 group의 lr=0.001 / weight_decay=0.0001이 일치한다.
- model.safetensors SHA-256: `99aad120127dd01275ac5b317839fa5f954fe84c302b8beca47407ad8036651e`, 기존 실행과 같다.
- history.json과 normalization.json은 기존 실행과 bytes가 정확히 같다.
- 원본 입력 135개와 실행 중 trainer bytes가 바뀌지 않았다.
- reload prediction 확인, MAE `0.029368045415302985rad`, 상수 기준 `0.005989848105380092rad`, verdict **reject**가 유지됐다.

새 policy revision은 `36c553f0a30372d640a37ce653ed24762493ccf1cd98f116c76b1657365073a9`이다.
동일 가중치라도 새 config/report/tool provenance로 별도 artifact가 된다.
이 대조 산출물은 연구 원장에 추가하지 않았으며 승격/설치 권한은 부여하지 않는다.

## 범위와 잔여 gate

이는 학습 설정 기록과 numerical 재현성의 증거이다. 평가 세트는 기존 것을 재사용했고
독립 SIM task, owner 실행, Fleet receipt, 장치 shadow/rollback 또는 현장 품질을 증명하지 않는다.
기존 Episode의 목표·명령이 각각 하나로 고정된 문제와 영상 라벨 검수는 별도로 해결해야 한다.
400-step 품질 비교와 데이터 적합성 진단은
[이전 기록](act-training-length-study-2026-10-04.md)을 유지한다.

독립 검토는 source 테스트 8 pass와 artifact equality/config-report 일치를 확인했다.
영향 검사 209 pass / 1 skip / 1 fail이다. 실패한 secrets guard는 기존 HEAD의
긴 hash/revision 문서 문자열 82개를 검출한다. 새 validation의 hash에는
SHA-256 문맥을 명시했고, 이번 변경으로 추가된 검출은 없다. guard 자체는 변경하지 않았다.
문서 배치 검사 15 pass / 1 Windows-bash skip이며 전체 gate가 통과한 것은 아니다.
