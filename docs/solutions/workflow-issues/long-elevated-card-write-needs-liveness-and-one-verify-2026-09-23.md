---
title: 한 시간짜리 관리자 권한 카드 쓰기는 세션과 분리하고, 진행 신호를 보고, 검증은 한 번만 한다
date: 2026-09-23
category: workflow-issues
module: deploy/sd (Windows SD writer, Pinky Pro release 2026.09.23-005)
problem_type: workflow_issue
component: development_workflow
severity: high
applies_when:
  - 관리자 권한으로 오래 도는 장치 작업(SD 카드 쓰기, 펌웨어 굽기)을 에이전트 세션에서 띄울 때
  - 외부 도구(rpi-imager 등)를 Start-Process -Wait로 기다리며 그 도구의 진행을 볼 수 없을 때
  - 같은 무결성 확인을 여러 도구가 각자 한 번씩 할 때
  - 하드웨어 식별자(디스크 시리얼) 하나로 대상을 고를 때
symptoms:
  - "005 카드 한 장에 약 3시간 30분: 세 번 시작, 두 번 실패, 한 번은 23분간 멈춘 줄 모름"
  - "세션이 끊기자 관리자 쓰기가 receipt·exit 표지 없이 사라짐"
  - "rpi-imager가 8,170 MB를 쓴 뒤 CPU·I/O 0으로 멈췄는데 Start-Process -Wait는 계속 기다림"
  - "리더기를 다시 꽂자 Get-Disk SerialNumber가 빈 값 (관리자 Update-HostStorageCache 뒤에도)"
root_cause: missing_tooling
resolution_type: workflow_improvement
tags: [sd-writer, rpi-imager, uac, liveness, verify-once, usb-serial, windows, pinky-pro]
---

# 한 시간짜리 관리자 권한 카드 쓰기는 세션과 분리하고, 진행 신호를 보고, 검증은 한 번만 한다

## Context

릴리스 2026.09.23-005를 `rosy-pinky-e4us` 카드(32 GB, 리더기 시리얼 `000000000207`)에 쓰는 데
약 3시간 30분이 걸렸다. 같은 카드로 004를 쓸 때도 48분이 걸렸다. 코드 결함보다는
**오래 도는 장치 작업을 다루는 방식**이 문제였다. 순서대로 이런 일이 있었다.

1. **확인 문구 불일치**. UAC 창에서 사람이 `ERASE SERIAL ...`를 입력했는데 맞지 않았다
   (프롬프트 끝의 `:`이나 한글 입력 상태로 보인다). 쓰기 전에 멈춰서 피해는 없었다.
2. **세션과 함께 사라진 쓰기**. `write-card.ps1`을 에이전트 셸의 백그라운드 명령으로 띄웠더니,
   세션이 끊길 때 관리자 쓰기도 receipt와 `.exit` 표지 없이 사라졌다. Imager 쓰기까지는 진행된 상태였다.
3. **시리얼이 빈 값**. 리더기를 다시 꽂자 `Get-Disk`가 `SerialNumber`를 빈 값으로 보고했다.
   관리자 `Update-HostStorageCache` 뒤에도 마찬가지였다. `UniqueId`의 USBSTOR instance ID에는 같은 시리얼이 남아 있었다.
4. **확인 없이 사라진 launcher**. 분리해 띄운 launcher가 로그 없이 끝났다. UAC 승인을 받지 못한 것으로 보인다.
5. **23분 동안 모르고 기다린 멈춤**. `rpi-imager --cli`가 8,170 MB를 모두 쓴 뒤, 자체 read-back 검증으로
   넘어가며 멈췄다. 스레드 5개가 모두 Wait였고 CPU·I/O가 0이었다. 스크립트는 `Start-Process -Wait`로 계속 기다렸고,
   "검증 중"이라는 추정만 사용자에게 전했다. 프로세스 CPU 시간과 `WriteTransferCount`를 두 번 재 보고서야 멈춤을 알았다.

그 사이 시간도 세 번 새고 있었다. 쓰기 전 raw 해시 계산(약 12분, Imager `--sha256`용), Imager 자체 검증(약 10분 이상),
우리 전체 readback(약 8분)이 모두 이미지를 다시 읽었다. 처음 둘은 셋째가 이미 더 엄격하게 하는 일이었다.

## Guidance

**1. 긴 관리자 작업은 에이전트 세션의 자식으로 띄우지 않는다.**
UAC 창 하나에서 전 과정을 돌리고, 자기 출력을 파일로 남기는 launcher를 `Start-Process ... -Verb RunAs -NoExit`로
띄운다. 이렇게 하면 세션이 끊겨도 작업이 계속되고, 승인이 거부돼도 원인이 로그에 남는다.

```powershell
# 한 번의 UAC로 정리·재시도까지 하는 launcher (이번에 쓴 형태)
Start-Transcript -LiteralPath $log
try {
    Get-Process rpi-imager -ErrorAction SilentlyContinue | Stop-Process -Force
    & powershell -NoProfile -File "$W\deploy\sd\write-card.ps1" -PlanPath ... -Confirmation "ERASE SERIAL <serial> <device>"
    "REWRITE_EXIT=$LASTEXITCODE"
} finally { Stop-Transcript }
```

**2. "진행 중"이라고 말하기 전에 진행 신호를 본다.**
외부 도구를 기다릴 때는 프로세스 CPU 시간과 I/O 전송량(`Win32_Process.WriteTransferCount`, `ReadTransferCount`)을
몇 초 간격으로 두 번 재서 변화를 확인한다. 둘 다 멈춰 있으면 멈춤이다. 앞으로는 writer가 이 감시를 직접 하고,
일정 시간 변화가 없으면 멈춤으로 판정해 실패로 끝내는 것이 맞다(후속 과제).

**3. 같은 무결성 확인은 가장 엄격한 한 곳에서 한 번만 한다 (D-180).**
- 입력이 진짜인지는 쓰기 전에 오프라인 서명된 `SHA256SUMS`로 압축 이미지 해시를 확인해 보장한다.
- 카드가 맞게 써졌는지는 `verify-media-readback.py`의 전체 readback 하나로 보장한다. 이 readback이 번들·receipt·registry의 관문이다.

그래서 raw 해시 사전 계산을 빼고, Imager는 `--cli --disable-verify`로 부른다.
이번에 멈춘 곳이 바로 Imager 자체 검증 단계였으니, 중복을 없애면 그 위험도 같이 사라진다.

**4. 하드웨어 식별자는 두 번째 출처와 그 출처를 믿을 조건을 함께 둔다.**
`SerialNumber`가 비었고 USB일 때만 `USBSTOR\...\<serial>&<n>`의 시리얼을 쓴다. Windows가 지어낸 ID
(`<digit>&<hash>&<n>`, 4자 미만)와 USBSTOR가 아닌 ID는 쓰지 않는다. 겹치면 항상 멈춘다(`fix/sd-usb-instance-serial`).
리뷰 지적대로, 싼 리더기들은 같은 가짜 시리얼을 공유할 수 있다. 시리얼은 카드가 아니라 리더기를 가리킨다.

**5. 사람에게 긴 문구를 치게 하지 말고, 치게 한다면 형식을 틀리기 어렵게 한다.**
계획을 사람이 확인한 뒤에는 `-Confirmation`으로 문구를 넘긴다. 사람에게 남는 판단은 UAC "예" 하나다.

## Applicability

- 다른 장치 굽기·펌웨어 작업(ESP32 플래시, OMX 설정 등)에도 1~3이 그대로 적용된다.
- 에이전트가 사용자에게 예상 시간을 말할 때는, 같은 장치로 잰 지난 기록을 근거로 한다(004 = 48분).
  기록 없이 짧게 말하면 신뢰를 잃는다. 이번에 "22:40", "22:50" 같은 추정이 여러 번 빗나갔다.
- 남은 후속 과제:
  - writer 안의 멈춤 감시
  - readback이 압축 스트림도 해시해 서명값과 대조 (리뷰 MEDIUM)
  - 부트 파티션 비파일 영역의 byte-exact 비교 (리뷰 MEDIUM)
  - 가짜 시리얼 리더기 경고 (리뷰 LOW)

관련: [D-173](../../adr/D-173-first-pinky-card-from-merged-release.md),
[D-180](../../adr/D-180-sd-write-single-authoritative-verify.md),
[guards-validated-only-against-synthetic-fixtures-2026-09-23.md](guards-validated-only-against-synthetic-fixtures-2026-09-23.md)
