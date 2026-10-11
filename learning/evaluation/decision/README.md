# 독립 사건 원장 비교

D-697의 host-only 소비자다. Fleet 원장 export와 고정 cohort를 JSON으로 받아 사건 결과 건수, 알려진 한계 비용, 남은 예약 책임과 비용 불명 시도를 비교한다. Fleet·Decision·ROS·모델 제공자를 import하거나 호출하지 않는다. 출력은 언제나 HOLD이며 정답 수용·모델의 해결 기여·승격·현장 수용을 승인하지 않는다.

```powershell
python learning/evaluation/decision/operational_comparison.py X:/DevTemp/<session>/cohort.json X:/DevTemp/<session>/case.json --out X:/DevTemp/<session>/comparison.json
```

입력은 각 파일 1MiB 이하로 제한하고 결과는 새 파일에 쓴다. UTF-8 BOM을 포함한 JSON도 읽는다. 기존 출력은 덮어쓰지 않는다. 두 역할 `model_feedback/1`과 선택적 인수 근거 `/2`, 단독 primary `/3`을 소비하고, 원문 제공자·개인 이름·payload를 결과에 복사하지 않는다.

cohort의 schema는 `rosy.incident.operational_cohort/1`이다. 닫힌 최상위 필드는 schema, domain, training, fit, evaluation, candidates다. training·fit은 session_id, recording_id, source_sha256 행 목록이다. evaluation은 여기에 subject_id, case_id를 더한 행 목록이다. 세 집합의 session·recording·원본 hash가 겹치면 거절한다. 평가 사건은 중복될 수 없다.

candidate는 strategy, strategy_sha256, profile_sha256, policy_revision, exports를 갖는다. strategy `primary`는 실제 단독 프로파일의 `/3`, `primary_reviewer`는 두 역할 `/1`·`/2`와만 연결한다(D-698). exports는 subject_id, case_id, digest 행 목록이며 평가 사건 집합과 정확히 일치해야 한다. 각 digest는 원래 case JSON과 전체 프로파일 목록을 결속한다. 변경·누락·중복·사용하지 않은 export는 거절한다. 전략을 실제 호출 횟수로 추정하지 않는다. 전체 목록 hash와 개별 모델 calibration hash는 서로 다르다.

known_marginal_micros는 실제 청구가 아닌 원장에 기록된 한계 비용의 합이다. reserved_liability_micros와 unknown_cost_attempts는 별도로 보존한다. 결과 불명을 비용 0이나 성공으로 바꾸지 않는다. outcomes는 원장의 관측 상태 건수이며 정확도나 인과적 성공률이 아니다.

현재 규칙 생산 기준, 독립 정답과 수용 한계, 정상 명령·재발의 완전한 추적 창, 실제 청구·운영 admission 근거가 부족하다. 단독 모델 생산은 source에 연결했지만 실제 Qwen 품질·현장 수용은 별도다. caller가 명시한 cohort·전략 hash도 데이터 출처 인증이 아니다. 따라서 누락 항목과 null을 남긴다. 두 역할 export를 규칙·단일 모델 자료로 가장하지 않는다. 다음 구현은 이 생산 경로와 출처 수용을 채우고 독립 비교 한계를 적용하는 것이다.

시험: `test/learning/decision/test_operational_comparison.py`와 기존 architecture 소유자·의존·크기 검사. pytest는 커밋된 HEAD를 적격 원격 호스트에 전달해 실행한다.
