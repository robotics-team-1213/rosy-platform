---
title: "새 로봇 연결은 현재 mDNS 광고와 승인된 접속 기록을 함께 확인한다"
date: 2026-10-30
category: workflow-issues
module: "Pilot collection / operator device discovery"
problem_type: workflow_issue
component: development_workflow
severity: medium
applies_when:
  - "새 SD 카드 개인화 뒤 로봇 이름이 바뀐 상태에서 수집 연결을 점검할 때"
  - "저장된 로봇 주소는 응답하지 않지만 현장 사용자는 연결됐다고 말할 때"
tags: ["mdns", "dns-sd", "pilot", "collection", "tls", "device-identity"]
---

# 현재 광고와 접속 기록을 함께 읽는다

## 배경

이전 로봇 두 대의 저장된 이름 조회와 SSH는 실패했다. 현장에서는 새 카드의
로봇이 연결돼 있었다. 서비스 광고를 조회하자 다른 이름의 장치가 나타났고,
기존 운영자 SSH host-key pin과 장치 이름·설치 릴리스를 확인해 접속할 수 있었다.
이전 이름들의 실패만으로 현재 연결된 로봇 전체의 상태를 판단한 것이 문제였다.

이 상황은 사이트 이름은 유지되고 주소만 바뀌는 경우와도 다르다. 새 개인화로
이름과 수집 대상 자체가 달라질 수 있으므로 운영자 기록과 현재 광고를 함께 본다.

## 확인 순서

1. 같은 LAN의 승인된 호스트에서 로봇 서비스를 조회한다.

   ~~~sh
   avahi-browse -r -t -p -k _rosy._tcp
   ~~~

   공통 adapter는 [discover.py](../../../contracts/foundation/core_common/discover.py)에 있다.
   특정 옛 이름의 DNS 조회 실패와 서비스 광고 조회 결과를 구분한다.
2. 광고는 접속 후보로만 사용한다. 기존 운영자 pin, 승인된 장치 기록과 실제
   장치 신원을 대조하고 StrictHostKeyChecking=yes로 접속한다.
   여러 후보가 있거나 신뢰 정보가 맞지 않으면 운영자에게 장치를 식별받는다.
   [SSH 절차](../../deployment/robot-ssh-access.md)를 따른다.
3. 모델 PC의 기존 수신 URL·CA·Operator 자격을 하나의 연결 기록으로 읽는다.
   native CORE와 미디어 gateway는 서로 다른 HTTPS 접속점을 제공할 수 있다.
   구성된 URL에서 CA와 인증서 이름, 인증 응답과 녹화 목록을 확인한 다음
   변경이 필요한 설정을 정한다. 다른 접속점에서 사용한 CA의 결과를 섞지 않는다.
4. 수신된 manifest·원본·영상 해시와 조작 짝, pending 등록 수와 재등록 결과를
   확인한다. 광고 발견, API 인증, 원본 수신, 물리 이동은 각각의 증거로 남긴다.

## 검증과 적용 범위

이 순서로 찾은 장치의 녹화 두 건을 모델 PC의 승인된 수신 경로로 처리했다.
운영 Learning에 925장이 pending으로 추가됐고 후속 두 실행은 각각 추가 0장이었다.
원래 검수 정보와 준비본·검수 사본 해시도 독립 확인했다. 근거는
[수집 검증 기록](../../validation/pilot-learning-collection-2026-10-30/result.md)에 있다.

이 교훈이 해결한 범위는 오래된 접속 목록 때문에 현재 장치를 놓친 진단과
접속점의 혼동이다. 이후 장치가 다시 응답하지 않은 현상은 별도 미해결 상태다.
현재 온라인 상태, 사람 승인이나 물리 주행 수용까지 이 기록으로 대신하지 않는다.

예방: 장치 재개인화 뒤에는 승인된 수집 대상과 실제 수신 URL을 먼저 대조하고
현재 서비스 광고를 확인한다. 주소·토큰·장치 UID·원본 영상은 교훈에 넣지 않는다.
