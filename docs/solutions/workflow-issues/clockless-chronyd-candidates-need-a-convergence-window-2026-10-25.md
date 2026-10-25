---
title: 새 chronyd 후보 측정은 초기 추정의 수렴 창을 따로 정한다
date: 2026-10-25
category: workflow-issues
module: deploy/hosts/common/rosy_time_sync.py
problem_type: workflow_issue
component: development_workflow
severity: medium
applies_when:
  - "운영 시계를 바꾸지 않는 새 chronyd -x로 NTP/NTS 후보를 측정할 때"
  - "작은 peer 지연과 큰 tracking 오차 상한이 함께 관측될 때"
tags: ["ntp", "nts", "chrony", "clockless", "startup", "measurement", "utc"]
---

# 새 chronyd 후보 측정은 초기 추정의 수렴 창을 따로 정한다

## Context

2026-10-25 chrony 4.8의 새 격리 daemon으로 공개 NTS 후보를 측정했다. 운영 daemon의 drift 상태를 복제하지 않고 `-x`와 빈 시계 capability를 사용했다. 최초 고정 70초 판정은 오차 상한 62.562초로 실패했지만, 인증된 peer 왕복 지연은 39.261ms였다. 이 결과만으로 시간원 자체의 정상 구간 품질을 판단할 수 없었다.

별도 사전등록 pilot은 같은 64초 polling과 `minsamples 4 maxsamples 4`를 유지하고 10·70·205초를 관측했다. 초기에는 skew 1,000,000ppm·frequency 0과 큰 dispersion이 함께 남았고, 205초에는 skew 105.428ppm과 상한 22.124ms를 관측했다. 새 추정기의 초기 상태가 짧은 판정에 영향을 준다는 실측 근거다. 첫 70초 실패는 그대로 보존한다.

## Guidance

측정 전에 목적·고정 관측 시점·primary 판정·정리 조건을 정한다. polling 간격과 초기화 조건에 맞춰 여러 갱신을 관측할 창을 마련하되, 실제 표본 수신이나 estimator 진입을 가정하지 않는다. 205초는 이 회차의 관측 창이며 다른 환경의 고정 권장값이 아니다.

tracking의 correction·root delay·root dispersion과 sample age·frequency·skew·update interval을 함께 기록한다. peer 인증·지연·분산은 별도로 남긴다. 작은 offset이나 peer RTT만으로 수용하지 않고, 제품 `assess`와 [D-859](../../adr/D-859-shared-utc-time-synchronization.md)의 기존 기준을 유지한다. RX 수는 독립 반복 수나 estimator 표본 수의 증거가 아니다.

기존 primary가 실패하면 그 기록을 유지한다. 더 긴 초기화 관측은 별도 설계·실행으로 남기고, 좋은 값이 나왔다는 이유로 종료 시점이나 임계값을 바꾸지 않는다. 단기 후보 통과와 운영 시간원의 독립성·윤초 정책·장기 안정성·전체 기기 수용을 구분한다.

격리 측정은 시계 제어를 비활성화하고 전용 PID·socket·runtime을 사용하며 NTP·UDP 명령 포트를 비활성화한다. OS가 독립 수명과 프로세스 그룹을 정리하게 한다. 운영 PID와 runtime 부모 보존·소유 자원 정리를 확인하지 못한 실행은 수용 근거에서 제외한다. 연결이 끊겼다고 운영 chrony를 재시작하거나 시계를 step하지 않는다. 정리 수명 이후 운영 상태를 읽어 확인하고, 실제 설정 변경은 기존 유지보수 절차로 수행한다.

## Why This Matters

새 daemon의 초기 불확실성과 지속적인 네트워크 지연은 다음 조치가 다르다. 둘을 섞으면 유효한 후보를 버리거나 polling만 바꾸며 같은 조사를 반복한다. 이 회차의 수렴 확인은 기존 운영 시간원의 문제나 전체 기기의 UTC 수용을 해결했다는 뜻이 아니다.

## When to Apply

운영 시계·drift 상태를 유지한 채 별도 daemon으로 시간원 후보의 추적 가능성을 조사할 때 적용한다. 후보별 1회·순차·비무작위 측정으로 공급자 우열이나 성공률을 주장하지 않는다.

## Examples

별도 고정 205초 pilot의 관측이다. 모두 같은 daemon 내부 관측이며 독립 반복이 아니다.

| 시점 | skew(ppm) | root dispersion | 제품 오차 상한 | 판정 |
|---|---|---|---|---|
| 10초 | 1,000,000 | 2.471초 | 2.491초 | 실패 |
| 70초 | 1,000,000 | 62.484초 | 62.504초 | 실패 |
| 205초 | 105.428 | 0.940ms | 22.124ms | 후보 통과 |

최종 계산은 `1.408561 + 39.550386/2 + 0.940308 = 22.124062ms`였다. 인증과 시계 권한 제거·제어 비활성·운영 PID/runtime 부모 보존·소유 runtime 정리 확인도 통과했다. 운영 source나 장치 설정은 바꾸지 않았다. 운영 시간원의 윤초 정책·장기 안정성과 장치별 50ms 수용은 이 측정으로 검증하지 않았다.

## Related

- [실패 귀속과 비교 조건을 분리하는 원칙](attribute-intermittent-failure-by-line-then-interleaved-comparison.md)
- [공통 UTC checker](../../../deploy/hosts/common/rosy_time_sync.py)
