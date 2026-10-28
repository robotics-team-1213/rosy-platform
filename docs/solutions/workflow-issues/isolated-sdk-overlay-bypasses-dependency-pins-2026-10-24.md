---
title: 전용 SDK venv도 임시 패키지 경로의 버전 변경을 막지 않는다
date: 2026-10-24
category: workflow-issues
module: OMX native ACT MODEL verification
problem_type: integration_issue
component: development_workflow
severity: medium
symptoms:
  - "실제 SDK 통합 시험은 통과했지만 임시 패키지 설치가 NumPy 고정 버전을 바꿈"
  - "전체 버전 검사를 추가하자 pytest 전에 Pillow 버전 불일치로 중단됨"
root_cause: config_error
resolution_type: environment_setup
tags: ["omx", "lerobot", "pythonpath", "dependency-pins", "sdk-verification"]
---

# 전용 SDK venv도 임시 패키지 경로의 버전 변경을 막지 않는다

## 증상과 원인

native 모델의 fixture Hub 왕복·새 프로세스 ACT 재적재 시험을 전용 SDK Python으로
실행했다. 실행별 출력 경로에 SciPy와 pytest를 설치하고 그 경로를 PYTHONPATH 앞에
놓았는데, 의존성 해결이 NumPy 2.4.6도 설치했다. 저장소 CPU 요구사항은 2.2.6이다.
첫 시험 자체는 PASS였으나 고정 환경의 수용 근거로는 제외했다.

원인은 전용 인터프리터의 경로만 믿고 임시 prefix의 전이 의존성을 제한하지 않은 것이다.
`deploy/robot/omx/requirements-lerobot-export.txt`의 고정 값은 별도 prefix 설치에
자동 적용되지 않는다. 패키지 설치 로그의 NumPy 2.4.6이 이 변경의 직접 근거다.

이후 전체 요구 버전 검사는 Pillow 10.2.0도 발견해 pytest 전에 중단했다.
그 실행에는 ROS wrapper에서 복사한 시스템 dist-packages 경로도 있었다.
경로 우선순위는 유력한 설명이지만 당시 Pillow module origin을 수집하지 않았으므로
그 패키지의 실제 import 위치를 확정한 것으로 표현하지 않는다.

## 해결과 복구

ROS가 필요 없는 시험에서는 시스템 패키지 경로를 빼고, 실행별 prefix에 NumPy와
Pillow도 각각 요구 버전으로 명시했다. SDK·추가 시험 도구의 버전 11개를 pytest 전에
검사하고 불일치하면 종료하도록 했다. 공용 venv는 수정하지 않았다.

실패하거나 다른 버전으로 통과한 실행은 그대로 보존하고 새 출력에서 검증한다.
버전 검사를 약하게 만들거나 이전 PASS를 새 환경의 근거로 바꾸지 않는다.
원래 실행이 종료·회수되기 전에 같은 시험을 중복 제출하지 않는다.

## 검증 근거

- 최초 실행은 실제 단일 팔 통합 시험 PASS였지만 설치 로그의 NumPy가 요구 버전과 달랐다.
- 다음 실행은 Pillow 버전 검사에서 EXIT1이며 pytest를 시작하지 않았다.
- 수정된 단일 팔 실행은 요구 버전 검사 통과, 실제 SDK 시험 1 passed / 0 skipped,
  전송 후 새 프로세스의 6관절 eval3와 processor 누락 거부를 확인했고 회수도 EXIT0였다.
- 소스·원자료 위치·해시와 양팔 검증은 [검증 기록](../../validation/native-model-readback-2026-10-24/result.md)에 둔다.

## 다음 적용 조건

전용 SDK 환경에 임시 과학 패키지를 더하거나 ROS wrapper의 PYTHONPATH를 재사용할 때
적용한다. 실제 실행 환경에서 요구 버전을 확인하고, 같은 패키지가 여러 경로에 있으면
module origin도 수집한다. 분리된 venv 이름이나 통합 시험의 PASS만으로 환경 준수를
주장하지 않는다. 이 해결은 fixture 전송·SDK 수용에 관한 것이며 실제 HF 전달이나
로봇의 과제 성공·장치 수용을 증명하지 않는다.
