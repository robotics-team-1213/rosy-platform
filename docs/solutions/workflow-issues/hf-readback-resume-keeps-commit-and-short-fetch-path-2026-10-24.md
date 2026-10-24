---
title: HF 전송 실패 뒤 업로드와 읽기 검증의 상태를 따로 복구한다
date: 2026-10-24
category: workflow-issues
module: OMX Hugging Face artifact delivery
problem_type: workflow_issue
component: development_workflow
tags: ["huggingface", "immutable-revision", "readback", "windows", "remote-evidence"]
applies_when:
  - "Hub 업로드 commit이 생성된 뒤 snapshot 다운로드 또는 로컬 증거 회수가 실패함"
---

# HF 전송 실패 뒤 업로드와 읽기 검증의 상태를 따로 복구한다

## 관측한 문제

private dataset 업로드는 commit을 만들었지만 이후 snapshot 다운로드가 HTTP429로
끝났다. 첫 작업의 upload.json은 남았고 성공 receipt는 없었다. 이어서 공식 원격
도구가 출력물을 로컬로 회수하다가296자 HF 임시 cache 경로의 tar.extractall
FileNotFoundError로 멈췄다. 프로세스 실패 하나로 업로드까지 실패했다고 판단하면
같은 데이터를 다시 commit하거나 이미 생성된 저장소를 지울 수 있다.

HTTP429는 요청 제한 응답이라는 증거다. 정확한 제한 bucket이나 경쟁 요청의 원인은
수집하지 않았다. 경로 길이는 Windows 제약과 부합하며 OS 경로 설정을 따로 입증하지
않았다. 이 기록은 관측한 복구 절차의 수용이며 모든429/파일 오류의 진단은 아니다.

## 복구 순서와 검증

1. 최초 durable job의 terminal 상태와 scope/cgroup/lock 해제를 확인한다.
   upload.json의 manifest와 immutable revision을 보존한다. 성공 receipt가 없으면
   bytes/reader 검증 성공으로 부르지 않는다.
2. 완전한 payload와 부분 readback cache를 별도 실행 소유 경로에 보존한다.
   manifest와 전체 payload SHA를 다시 비교한다. 최초 job을 재제출하지 않는다.
3. 같은 upload.json을 사용해 기존 `hub_sync.upload_bundle`의 resume 경로를 실행한다.
   이 관측에서는 외부 API adapter의 create_repo/create_commit를 모두 거절하고
   downloader에도 기존 revision만 허용했다. 최신 HEAD로 입력을 바꾸지 않는다.
4. 관측한 복구는5분 이상 대기, max_workers1, 기존 cache를 사용했다.
   대기 시간·worker 수를 보편적인429 해결 설정으로 취급하지 않는다.
5. 로컬 출력 경로를 짧게 두고 회수를 다시 확인한다. 실제 HF readback과 로컬 회수의
   상태를 따로 기록하고, 회수 후 payload/readback 전체 SHA와 receipt를 대조한다.

실제 관측은 기존 commit을 유지하며 새 저장소 쓰기0으로1613파일/1587프레임을
검증했다. 짧은 경로의 coordinator는 EXIT0으로 끝났고 로컬 payload/readback의
각1613파일도 manifest와 일치했다. SDK 버전·import 위치와 실행별 prefix 검사는
기존 [SDK 교훈](isolated-sdk-overlay-bypasses-dependency-pins-2026-10-24.md)을 적용했다.
자세한 source/manifest/receipt/종료 증거는
[왕복 검증 기록](../../validation/omx-hf-private-roundtrip-2026-10-24/result.md)에 있다.

## 다음 적용 조건

Hub commit이 이미 생긴 뒤 다운로드·reader·로컬 회수 중 하나만 실패할 때 적용한다.
먼저 같은 commit과 파일 집합인지 확인하고 읽기만 재개한다. upload.json이 없거나
원격 commit 여부가 불확실하면 확인부터 하며 새로운 업로드로 덮지 않는다.
전송 수용은 모델 task 성공·장치 실행·정책 승격과 별도다.
