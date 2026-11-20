---
title: R 콘솔의 "건강한 팔"은 손으로 패치한 이미지의 가짜였고 셀 미러 환경 키는 비어 있었다
date: 2026-11-20
category: workflow-issues
module: operations/fleet (recognition/workcell_observations.py), deploy/robot/omx (observation bridge, arm-status bridge), tools/remote/workcell_pipeline_gate.py
problem_type: workflow_issue
component: development_workflow
severity: high
root_cause: unreviewed_hand_patch_and_empty_config
resolution_type: tooling_addition
symptoms:
  - "Fleet R 콘솔에 OMX 팔 세 대가 늘 신선(fresh)하고 건강하게, 값이 전혀 바뀌지 않은 채 보였다"
  - "운영자는 셀에서 R로 가는 파이프라인이 살아 있다고 믿었지만 R는 팔 관측을 한 건도 받지 못했다"
  - "셀 카메라 영상도 R에 닿지 않았다"
applies_when:
  - "R 화면에 셀 데이터가 보이거나 안 보여서 파이프라인 상태를 판단해야 할 때"
  - "R 이미지를 손으로 고치거나 .py를 이미지에 직접 COPY하려 할 때"
  - "팔이나 카메라 상태가 '정상'인데 값이 움직이지 않을 때"
tags: [fleet, workcell, observation-mirror, hand-patch, fake-data, stale, overlay, signed-image, pipeline-gate]
---

# R 콘솔의 "건강한 팔"은 손으로 패치한 이미지의 가짜였다

## 증상

R 콘솔은 팔 세 대를 신선하고 건강하다고 보여 주었고 값은 한 번도 변하지 않았다. 실제로 R는 팔 관측을 받은 적이 없었다. 건강해 보이는 화면이 파이프라인이 살아 있다는 증거로 읽혔다.

## 원인

1. **R의 손 패치 이미지(가짜 표본).** 검토 없는 overlay 층으로 만든 R 현장 이미지(브랜치 `keep/r-live-20261117`, 커밋 aaf1bfe90a에 보존)가 `workcell_observations.py`의 `snapshot()`에서 "표본 없음" 분기를 합성 팔로 바꿔 놓았다. fresh=True, 고정 epoch, sequence 1, captured_at=지금, 고정 세션 id, 모든 모터 raw 2048 / 45 mA / 31 C. main에는 없던 코드였고 서명 이미지 260da907f0에서 사라졌다. 표본이 없을 때 "없음"을 말해야 할 자리에서 건강함을 만들어 냈다.
2. **셀 미러 환경 키가 비어 있었다.** 셀의 관측 브리지와 팔 상태 브리지에는 D-1053 미러 코드, 맞는 자격 증명, R CA가 이미 있었다. 그러나 `ROSY_OBSERVATION_MIRROR_FLEET`, `ROSY_OBSERVATION_MIRROR_VISION`, `ROSY_ARM_STATUS_MIRROR_FLEET`이 비어 있어 카메라도 팔도 R에 가지 않았다. 코드가 있다는 것과 켜져 있다는 것은 다르다.
3. **설계 빈틈(별도 수정, 브랜치 `feat/omx-observer-session-handoff`).** 팔 A·B의 유휴 관측기는 세션에 직렬 포트를 내주지 않아 10-24부터 꺼져 있다. 그래서 A·B는 세션 밖에서 아무것도 보고하지 않는다. 이때 올바른 표시는 정직한 UNKNOWN이다.

## 해결

- R를 서명 이미지로 옮겼다.
- 셀에 미러 환경 키를 설정했다(백업 `*.bak-*-r-mirror` 보존).
- 읽기 전용 게이트 `tools/remote/workcell_pipeline_gate.py`로 검증했다: 28개 검사 통과. 셀 카메라 6대 모두 R 프레임 200, 나이 100 ms 미만, arm_s sequence가 셀과 R에서 함께 증가(지연 약 0.1 s), 가짜 표식 0건.

## 다음에 적용할 판별 규칙

- fresh=true인데 epoch나 sequence가 올라가지 않거나, epoch와 세션 id가 고정이거나, 모터 값이 전부 같으면 가짜다.
- 셀과 R의 sequence를 나란히 비교한다. R 화면의 "건강함"만 믿지 않는다. 손으로 패치한 이미지의 패널은 증거가 아니다.
- R에 셀 데이터가 없으면 먼저 셀의 미러 환경 키가 채워져 있는지 본다.
- 표본이 없는 분기는 UNKNOWN을 돌려주어야 한다. 합성값을 채우는 코드는 어떤 이유로도 넣지 않는다.

## 복구

- 미러를 되돌리려면 `*.bak-*-r-mirror` 파일에서 환경 줄을 되돌린다.
- R 이미지에 .py를 손으로 COPY하지 않는다(옛 pyc가 남아 옛 코드가 돌고, 검토되지 않은 코드가 들어간다). 변경은 main 착지 후 서명 이미지로만 배포한다.
