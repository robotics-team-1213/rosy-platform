# 명시적 FULL 변경의 충전 통합 실패와 동일 호스트 대조

2026-10-27. [집중 소스 검증 기록](../land-explicit-full-2026-10-27/result.md) 이후의 공식 착지 시도와 대조 실험을 고정한다. 이 기록은 FULL 통과나 원인 해결, 게시·배포·장치 수용의 증거가 아니다.

## 실패한 공식 실행

고정 후보는 로컬 `3d199fe1d11f62c845debe2b4f77ff777f9dfa2c`, 실패 당시 main 기준선은 `cbe4cfe3cf204939b4e1c132283a4243ea62b1b4`다. 후보는 승인된 source 7개·시험 4개·문서를 보존하고 main의 패널 계약 수정을 정상 병합했다. 독립 보존 검토를 통과했다. 실행은 공식 `tools/land.py --tests auto --no-cache`이며 모델·AI 시험 PC만 사용했다. 두 PC의 시작 시 저장 공간은 각각 113.431/208.984GiB, 사용률 73.45/52.88%로 사전 기준을 충족했다.

guard 290초는 architecture 287 PASS, collection 2,138 PASS/1 SKIP, alone 20 PASS/1 SKIP였다. SKIP은 반대 모드의 빈 parameter이며 요청한 단독 실행 20개는 완료됐다. 세 known 분류는 NEW0/known0/flaky0다.

본시험은 25개 호출 중 11개만 완료했다. 결과는 중복 포함 **15,697 PASS / 562 SKIP / 1 FAIL**이며 나머지 14개 호출은 취소·미실행이다. Fleet 묶음은 7,031 PASS/391 SKIP/0 FAIL이었다. 실패 묶음은 Gateway·events·services·shared web·foundation·device profile 묶음으로 1 FAIL/7,744 PASS/91 SKIP였다. 브라우저 opt-in 전체 실행이나 FULL 성공을 주장하지 않는다.

실패 node는 다음 하나다.

```text
middleware/core/gateway/test/test_station_camera_pipeline.py::test_station_camera_http_pipeline_aligns_then_requires_contact_and_measured_stop[lifespan]
```

전체 묶음에서는 departure renewal의 실제 1.5초 제한 안에서 SQLite 작업을 기다리다가 `CHARGE_DEPARTURE_UNVERIFIED`가 발생했다. 후보 단독 재실행은 더 앞선 SEATING 검사에서 HOLD/`STATION_LOCAL_EVIDENCE_INVALID`로 실패했다. 같은 node라도 최초 원인이 같다고 합치지 않는다. 단독 실패는 AI PC, main 단독 통과는 모델 PC여서 이 비교만으로 branch 원인을 확정할 수 없다. 공식 실행은 exit1로 중단했으며 착지·receipt는 없다.

## 변경 경로와 시계 경계 조사

조사한 product 3,953경로, 실패 시험·fixture·conftest·의존성·runner 설정은 후보와 기준선 사이에 동일했다. 선택된 package와 단독 호출에서 변경된 Tool1 helper를 import하거나 읽어 실패 경로로 이어지는 구체적인 연결은 찾지 못했다. controller와 선행 실행 맥락의 영향까지 배제한 것은 아니다.

기존 시험의 관측에도 제한이 있다. station owner는 HOLD 뒤 tick에서도 reason을 덮어쓸 수 있고, 시험은 SEATING만 기다리며 SIM을 더 진행하므로 최종 reason이 최초 원인을 가릴 수 있다. 이미지·HTTP·SQLite 작업에는 실제 asyncio 시간이 쓰인다. SIM 증거 만료, thread 대기, SQL 잠금·commit, event-loop 복귀 지연을 아직 분리해 입증하지 못했다.

제품 코드·시험 timeout·SQLite durability·quarantine은 변경하지 않았다. 기존 간헐 실패 교훈에 따라 실패 줄과 실제 실행 호스트를 먼저 비교했다.

## 동일 AI 호스트의 제한된 교차 비교

AI만 허용한 공식 runner로 후보 C1 → 기준선 M1 → 후보 C2 순서로 위 exact node를 실행했다. 세 실행은 동일한 실제 SSH target, env `99f93e0587919545`, freeze `279c2df20eca6924`, 같은 `-q -rP` 옵션을 사용했다. 실제 target 값은 기록하지 않는다. 각 실행 전 저장 공간을 새로 확인했다.

세 실행 모두 exact node의 `. [100%]`, 공식 runner exit0, known NEW0/known0/flaky0를 확인했다. quiet 옵션이 중복돼 일반 `1 passed` 요약줄은 없었다. 없는 문구를 만들거나 exit0만으로 빈 선택을 통과로 해석하지 않았다. SKIP·deselect·실패 표시는 없었다. 세 범위는 같은 node의 반복이므로 고유 시험 수로 합산하지 않는다.

다른 세션의 부하는 통제하지 못했다. 이 비교는 **동일 호스트에서의 비재현 증거**이며, 원인 부재·부하 귀속·전체 package 실행 맥락의 동등성을 증명하지 않는다.

## 증거 위치와 무결성

원본은 `%LOCALAPPDATA%/Temp/rosy-land-explicit-full/` 아래에 있다. `failed-full-3d199/`의 raw 16개는 원본과 복사본 해시를 대조했고 독립 감사에서 호출과 일치함을 확인했다. 이전 실행의 미완료 pre23 파일은 이번 증거에서 제외했다. `charge-ai-c1/`, `charge-ai-m1/`, `charge-ai-c2/`는 각각 새 log-dir이며 runner·known 로그도 별도 보존했다.

| 파일 | SHA-256 |
|---|---|
| failed-full-3d199/console.txt | D1247C22A558D00C97726E3E0294B3812F1CBF6B7B78FC26E74108EC0C553F06 |
| charge-ai-c1/run-1.txt | 238405ed3418f978805a282316e319f79e591a86b639b4cf96d3a41c915ad28a |
| charge-ai-c1-runner.txt | 45b4c8b89adc8d8f0479d721bf7e1327a0ed22c0c805770ee6dfb09bacdb5c05 |
| charge-ai-c1-known.txt | c596e65a18fcf0e24850d24002104b5e2a9f97bbd8ab2b700423efa308b46c6e |
| charge-ai-m1/run-1.txt | 75da76653808e17ba91006b6cbbc7863c5d405f6993456d78e90b664c01e4d82 |
| charge-ai-m1-runner.txt | 91bbdcd0ba26c4ffd09111b2c00bb1c55a66081c81071b60aee9d9544ed59e7b |
| charge-ai-m1-known.txt | c596e65a18fcf0e24850d24002104b5e2a9f97bbd8ab2b700423efa308b46c6e |
| charge-ai-c2/run-1.txt | 63311f521098e5406bc334f64e9e3629b3429d50cf1be1f28db304d846bbf8bf |
| charge-ai-c2-runner.txt | fcd6087f07005f799bbdbc356c5446dcf288484c40b9a82ade51829e4e0c5629 |
| charge-ai-c2-known.txt | c596e65a18fcf0e24850d24002104b5e2a9f97bbd8ab2b700423efa308b46c6e |

## 다음 실행 조건과 한계

독립 검토는 세 control의 실행·SHA·호스트·argv 보존을 조건으로 새 공식 whole FULL 1회를 허용했다. 현행 main 통합·보존 검토, guard/isolation 및 canonical FULL을 생략하지 않고 body cache를 사용하지 않는다. 재실패하면 반복을 멈추고 기존 시험 probe에서 최초 HOLD와 SQL·상태 전이 시각을 계측한 뒤 판단한다. 새 실행 결과는 이 고정 기록을 고쳐 쓰지 않고 별도로 남긴다.

현재 원인은 미해결이며 새 FULL·착지·게시·native build·site/robot 배포·NTP 정밀도 수용은 이 기록에서 완료로 표시하지 않는다. CE: 미해결 — 원인 귀속 자료가 부족하여 새 해결 교훈을 쓰거나 기존 실패를 무효화하지 않았다.
