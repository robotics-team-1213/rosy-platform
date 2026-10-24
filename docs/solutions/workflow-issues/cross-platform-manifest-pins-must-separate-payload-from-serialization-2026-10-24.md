---
title: 교차 플랫폼 전송은 파일 bytes와 manifest 직렬화를 따로 고정한다
date: 2026-10-24
category: workflow-issues
module: OMX Hugging Face artifact delivery
problem_type: workflow_issue
component: development_workflow
tags: ["huggingface", "windows", "crlf", "manifest", "artifact-integrity"]
applies_when:
  - "Windows에서 검토한 전송 묶음을 Linux에서 다시 준비해 해시를 비교함"
---

# 교차 플랫폼 전송은 파일 bytes와 manifest 직렬화를 따로 고정한다

## 관측과 원인

Windows에서 준비한 모델5파일과 카드를 Linux 전용 SDK 환경에서 다시 묶었다.
검토한 카드를 read_text로 읽고 원격 write_text로 다시 만들자 CRLF가 LF로 바뀌어
파일 SHA가 달라졌다. 카드 bytes를 보존한 다음 실행에서는6파일 SHA가 모두
일치했지만 manifest JSON 자체의 CRLF/LF 차이로 원본 manifest SHA 검사가 막혔다.
두 중단 모두 HF 쓰기 전이었다. 고정 byte SHA는 JSON 의미의 동일성을 뜻하지 않는다.

## 적용한 해결과 검증

검토한 카드의 bytes를 전달하고 write_bytes로 저장했다. manifest는 검토한 같은
문서에서 UTF8·ensure_ascii=false·indent2·allow_nan=false·끝 LF로 직렬화하는
규칙을 정해 별도 SHA를 고정했다. 최상위 키는 repo_id→repo_type→files 순서,
files 키는 상대 경로 오름차순으로 고정했다. preview 원본 SHA도 보존했다.
실제 payload6파일의 경로·해시는 변경하지 않았고, 두 manifest의 파싱 결과와
모든 파일 해시의 동일성을 확인한 뒤 Linux raw manifest가 정한 canonical bytes와
정확히 같은지 확인했다. 임의 줄바꿈 변환으로 검사를 통과시키지 않았다.

최종 프로토콜은 업로드 전에 canonical raw SHA를 요구하며, actor-free 자체 검사도
5개 모델 파일의 고정 SHA와 원래 카드 bytes에서 같은 manifest를 재구성한다.
실제 원격 preflight와 private HF 전달·ACT 재적재가 이 결속으로 통과했다.
원본·수정 전 실패·수정 후 SHA와 출력 증거는
[모델 왕복 기록](../../validation/omx-hf-model-roundtrip-2026-10-24/result.md)에 있다.

## 다음 적용 조건

검토한 파일을 같은 SHA로 전달해야 하면 text mode로 재생성하지 않는다.
manifest를 다시 생성해야 하면 payload SHA 목록의 동일성과 문서의 정확한
직렬화 규칙을 각각 검증한다. 예외 진단은 파일 basename/line 같은 안전한 위치를
기록해 SDK 원문·자격증명을 출력하지 않고도 어느 결속이 실패했는지 확인한다.
