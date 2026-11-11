---
symptom: "게시용 FULL 등급에서 24개 id가 실패하고 전부 main에서도 실패(MAIN-RED) — 원인은 코드가 아니라 외부 아카이브 접속 불능"
discovered: 2026-11-11
category: test-failures
tags: [rauc, pinned-download, network-outage, main-red, full-tier, mirror-fallback]
---

# 하나에 고정된 시험 다운로드 소스는 장애 날 때 MAIN-RED로 위장한다

## 증상

게시용 무캐시 FULL(`docs/publish-full-20261111`, 커밋 99120b86f6)에서 24개 id가 실패했다.
단독 재시험과 main 재시험에서도 같이 실패해 착지 게이트는 「main가 깨졌다」(MAIN-RED)로
판정하고 게시를 막았다. 실패 원인은 전부 같은 한 줄이었다:
`test/os_rauc_fakes.py`의 `Pinned RAUC package unavailable`.

## 원인

RAUC 픽스처가 고정한 패키지를 `archive.ubuntu.com` 한 곳에서만 내려받았다. 그 시각
시험 PC 양쪽에서 `archive.ubuntu.com`(및 같은 호스트를 가리키는 `kr.`)이 curl 000로
접속 불능이었다(github.com은 200 — 랩 네트워크에서 우분투 아카이브 쪽만 막힘).
외부 다운로드가 껴 있는 시험의 네트워크 실패는 **코드 회귀와 똑같은 모양으로 MAIN-RED에**
나타난다. 진단은 시험 PC에서 접속 행렬(github/아카이브/미러)을 직접 재야 했다.

## 해결

`test/os_rauc_fakes.py`의 `download_package`가 `/ubuntu/` 핀에 한해 같은 pool 경로의
kernel.org 우분투 미러로 폴백한다(각 URL 3회 시도). 크기·sha256 핀이 원본 무결성을
보장하므로 응답한 출처가 어느 쪽이든 검증은 동일하다. 두 계약을 그대로 지켰다:

- 진단문은 종래 양식 `attempt N: <관측>`만 쓰고 **URL을 담지 않는다**(핀 쿼리에 비밀이
  있을 수 있다 — 기존 시험이 `never-log` 누출 금지로 고정).
- 미러 폴백 복구를 고정하는 신규 시험을 추가했다(아카이브 3회 실패 → 미러 성공).

첫 구현은 시도를 3→2로 줄이고 URL을 진단에 박아 기존 6건의 계약 시험을 깨뜨렸다 —
시험이 진단 계약을 소유하고 있다는 점을 먼저 읽었어야 한다.

## 검증 근거

- 원격(ai 호스트) `test_os_rauc_tool.py`·`test_os_rauc_service.py`·
  `test_prepare_os_release.py` 50 passed — 그 시각에도 아카이브가 다운 상태라 픽스처가
  미러 폴백으로 실제 패키지를 받았다(종단 검증).
- 미러 파일 sha256 `78770edf…fad7`·160646 바이트로 핀과 일치(모델 PC에서 확인).

## 재발 방지

- 시험이 외부 URL에서 내려받는다면 폴백 후보를 달아 두고, 핀(크기·해시)으로 무결성을
  보증한다.
- MAIN-RED 판정을 받으면 실패 id의 근본 예외부터 본다 — 네트워크 예외(OSError·
  IncompleteRead·curl 000)가 여러 id에 같은 모양으로 반복되면 코드가 아니라 인프라다.
- 진단 메시지에 URL 전체를 넣지 않는다(기존 계약). 어떤 URL이 실패했는지는 호출 순서
  시험으로 고정한다.

## 다음에 적용할 조건

`test/`의 고정 다운로드 픽스처를 새로 쓰거나, MAIN-RED의 근본 예외가 네트워크류일 때.
