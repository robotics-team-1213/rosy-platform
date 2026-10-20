# 실측 건강도 정책 구현과 원격 회귀

날짜: 2026-10-17. 원격 시험된 커밋: `65a26cbd61`. 제품 정책 커밋: `57a136d87f`. 반례 선행 커밋: `31b704b79f`. 전체 작업 기준: `ee0153823ab8b4b464cb2ceb33929af71da642ac`.

## 구현과 한계

Fleet 기존 `ChargePolicyAdmission`에 실측 정책을 추가했다. 설치된 로봇별 source 종류와 capacity revision을 복사해 고정하고, 기존 원본 수명·팩·예산 검사 후 긍정 판정에 SOH/사용 가능 Wh/온도를 요구한다. WAIT/maintenance 우선순위와 별도로 승인된 기존 보수적 정책은 유지한다. 실제 app bootstrap은 같은 measured policy 인스턴스를 요구한다. 기존 runtime 최종 작업 전송과 departure 재검사가 이 정책을 사용한다.

이것은 실측 건강도 운영의 P1 admission 경계다. source 종류/capacity 등록은 원본 공급자 attestation이나 교정·실기 capability가 아니다. 실제 vendor reader, hardware factory, native/HTTP parent 결합, OMX 예약/interlock, 지도 생산자 운영 기동, 지속 운영 용량과 물리 수용은 미완료다. 스테이션 실기 생성 경로는 계속 닫혀 있다.

## 실제 실행 기록

모두 공식 `tools/remote/remote_pytest.py --log-dir <외부 경로> -- <대상>`으로 커밋된 소스를 실행했다. 노트북 pytest·시뮬레이터·장치 변경·운행·배포·merge/push는 수행하지 않았다.

| 커밋/대상 | 관측 결과 | 외부 로그 |
|---|---|---|
| `31b704b79f`, 새 반례 | 23 FAIL/NEW 23. 기존 bootstrap의 미거절과 미구현 measured class 실패를 확인 | `C:/DevTemp/station-charge/measured-health-red/run-1.txt` |
| `57a136d87f`, 최초 GREEN 요청 | 잘못된 departure 파일명으로 exit 4, 수집·실행 없음. 통과로 계산하지 않음 | `C:/DevTemp/station-charge/measured-health-green/run-1.txt` |
| `57a136d87f`, 수정된 Fleet 7개 파일 | AI PC 112 PASS/0 skip/NEW 0, exit 0 | `C:/DevTemp/station-charge/measured-health-green-corrected/run-1.txt` |
| `57a136d87f`, 에너지/native/계약 15개 파일 | 모델 PC 581 PASS/2 FAIL/NEW 2 | `C:/DevTemp/station-charge/pack-energy-restored/run-1.txt` |
| `65a26cbd61`, 합동 22개 파일 | 모델 PC 696 PASS/0 skip/NEW 0, exit 0, 38 warnings, 51.21초 | `C:/DevTemp/station-charge/pack-energy-restored-corrected/run-1.txt` |

마지막 합동 결과를 최종 집계로 사용한다. 앞선 통과 수와 더하지 않는다. 각 실제 결과를 `python test/known_failures.py <run-1.txt>`로 비교했다. 실패를 baseline에 추가하지 않았다.

회귀 2개 실패의 원인은 기존 map 경합 시험이 설치 후 Ledger clock callable을 교체해 energy source와의 동일 시계 계약을 깨뜨린 것이다. 시험 전용 수정으로 같은 callable 내부의 capture 이후 hook을 사용해 원래 경합을 보존했다. 실제 시계 교체는 같은 값을 반환해도 ZERO/STOPPED가 되어야 하는 별도 반례를 추가했다. 제품 제어·시계 검사를 완화하지 않았다.

## 최종 시험 범위

Fleet 7개: `test_charge_measured_admission`, `test_charge_bootstrap`, `test_charge_runtime`, `test_charge_policy`, `test_charge_redeployment`, `test_charge_recovery`, `test_charge_return` (`operations/fleet/test/`).

CORE services 4개: `test_execution_pack_energy`, `test_execution_budget`, `test_execution_ledger`, `test_native_map_adoption` (`middleware/core/services/test/`).

Gateway 7개: `test_native_execution_binding`, `test_execution_writer_fence`, `test_execution_source_bootstrap`, `test_execution_odometry`, `test_execution_native_map`, `test_execution_map_observation`, `test_event_catalogue` (`middleware/core/gateway/test/`).

루트 4개: `test/architecture/test_safety_separation.py`, `test/test_behavior_test_ownership.py`, `test/architecture/test_module_structure.py`, `test/test_harness_contracts.py`.

## 검토와 남은 gate

제품 커밋 전 독립 scoped 안전 검토 PASS와 trailer를 받았다. 최종 독립 code review 및 시계 fixture 변경 검토도 PASS다. 변경 Python 6개 AST, diff 형식, 3개 커밋의 safety_review/size_range 검사를 통과했다.

이 결과는 G0의 해당 CPU 회귀 근거를 채우며 필수 FULL CI를 완료하지 않는다. 기존 전체 브랜치의 FULL 요구는 유지한다. 실제 카메라 교정·BMS/충전기·SOH 품질/신선도·전기 분리·정지/암 영역 인계와 3회 실물 주기/위치 변경/지속 운행의 수용 근거는 없다. 현장 확인은 기존 응답대로 이후 가능 시점에 진행한다.
