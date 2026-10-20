# 운행 중 지도 기준 상실 정지 검증

전체 스테이션 목표는 ACTIVE다. 실제 CORE manager/HTTP/native parent/sole writer를 검증했으며 위치·TF·지도 readback은 합성이다. 실기 정밀도·물리 정지 시간·전체 복귀/충전/재투입 수용을 뜻하지 않는다.

## 결함과 수정

LOCALIZED 상태 이름이 유지되는 동안 pose_frame만 map→odom으로 바뀌면 신규 admission은 거절됐지만 진행 중인 운행의 on_lost는 호출되지 않았다. LocalizationAssist가 admission과 같은 LOCALIZED/map predicate를 공유하고, 이 유효 조건의 변화를 공개 state 이벤트의 dedupe와 별도로 추적하도록 바꿨다. 기존 gate를 유지한 채 기존 autonomy_halt를 호출한다. 공개 DTO·event 필드·state-only 이벤트 의미는 바꾸지 않았다.

첫 invalid 보고는 그 전에 시작한 ordinary autonomy도 정지 대상으로 만든다. 보고 자체가 없는 legacy 동작은 유지하고, 이후 invalid→invalid는 중복 정지하지 않는다. 첫 LOCALIZED/odom을 취득 완료로 알리지 않는다. map 복구는 기존 on_localized 취소/re-plan 경로를 쓰며 소비된 parent Budget나 이전 운행을 자동 복원하지 않는다. 기존 localization mission은 reported-invalid 상태에서 계속 새로 시작할 수 있다. 첫 보고 전에 시작한 mission은 invalid 보고 경계에서 기존 halt/IDLE 처리의 대상이 된다.

## Revision과 실제 원격 결과

| Revision | 결과 |
|---|---|
| `04db6a2f66` | 승인 AI PC4대상 **146 PASS/8 FAIL**, exit1. 모두 동작 assertion 반례이며 missing API/setup 오류가 아니다 |
| `d0fd038c43` | 독립 D-430 source 검토 후13대상 **375 PASS/2 FAIL/0 SKIP/NEW2**. 실제 pytest는 종료됐고 로그를 받은 뒤 driver가 cp1252로 한국어 assertion을 출력하다 UnicodeEncodeError로 종료했다 |
| `fa0279c11c` | 독립 검토 후14대상 **387 PASS/0 FAIL/0 SKIP/NEW0**, exit0. 기존 첫-invalid 취소 카운터를 취득 callback과 분리하고, 아래 tuple 모호성을 정리했다. driver stdout에 PYTHONIOENCODING=utf-8을 명시했다 |

두 번째 실행의 실패 중 하나는 첫 CANDIDATES 보고의 새 정지를 포함한 기존 HTTP 취소 횟수 기대값이었다. 첫 정지를 별도로 확인한 뒤 카운터를 비우고 취득 callback 한 번을 확인하도록 고쳤다. 독립 검토에서도 기존 never-localized unit oracle과 첫-invalid 규칙의 충돌을 찾아, no-report legacy 허용→첫 UNKNOWN 한 번 정지→후속 invalid dedupe를 명시했다.

나머지는 event guard가 앞선 native-map client의 `(pending-dict, empty-dict)` 다중 대입 RHS를 dynamic event tuple로 읽은 것이다. 같은 RLock 안에서 callback 전에 두 순차 대입을 끝내도록 풀었고 캡처·detach·취소 순서를 유지했다. scanner·allowlist·baseline·threshold를 완화하지 않았다. 이 수정도 독립 scoped PASS 후 커밋했다.

실행한 동작은 tick 또는 상태 메시지의 frame-only 상실, HTTP 진행 운행 취소와 후속 admission 거절, line-follow OFF, gate check/start 중 frame loss의 직렬화, MANUAL 유지, map 복구 후 비재개, 지도 readback이 아직 유효한 실제 native NAV/dock parent 소비다. original TF 수명→frame flag→LocalizationAssist→실제 Nav cancel/IDLE→다음 wheel 출력 ZERO도 실행했다. 이 시험은 새 odom callback이나 새 localization state 없이 진행하며 물리 TF/장치를 사용하지 않는다.

14대상은 localization assist/docking gate·HTTP/mission/cross-lane·native map integration/native binding·original TF·event catalogue·safety/ownership/module structure/C6·실제 Future client orchestration이다. 실제 generated DDS 및 native producer 검증은 이번에 반복하지 않았으며387건과 합산하지 않는다. 원본 로그는 저장소 밖 `C:/DevTemp/station-charge/localization-frame-loss-red/`, `localization-frame-loss-green/`, `localization-frame-loss-regression-green/`에 있다. 실제 summary/exit와 known_failures0new/known/flaky를 확인했다.

## 남은 범위

[native writer 검증](../station-native-map-writer-2026-10-17/result.md)의 required map 슬롯과 실제 clients를 supported private 운영 factory에 결속하고 actual native readback/original odom·Fleet 승인 map revision/변환·geometry/localization·원본 pack energy/SOC/SOH/reserve를 검증해야 한다. owner parent64개/global nonce65,536개(두 role4Hz이면8,192초) 장시간 수명과 운영 failed-config cleanup도 미해결이다. 전체3회 복귀·충전·재투입과 station relocation·ARM64/DEVICE/FIELD, FULL CI와 기존 branch ancestry guard도 남아 있다. 현장 담당자는 나중에 확인 가능하며 장치 재탐색·이동·토크·재시작·배포·landing·push는 하지 않았다.
