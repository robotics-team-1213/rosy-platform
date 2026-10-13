# D-715 원장 사건 inventory와 독립 비교의 누락 검증

**Status:** Accepted (2026-10-12, source contract)

기존 모델 사건 exporter와 별도로 root 도구가 같은 Fleet DB의 owner/policy/전체 profile tuple·시작 시간 창에 해당하는 보존 사건 행을 읽기 전용 트랜잭션으로 목록화한다. ACTIVE·HOLD·NOT_NEEDED를 모두 포함하며 실패/UNKNOWN 후보를 caller가 임의로 제외하지 않는다. 목록은 최대 1,000건이고 초과는 잘라서 수용하지 않는다. 제공자·개인 정보·DB 경로·원문 payload는 출력하지 않는다.

내부 schema rosy.incident.case_inventory/1은 scope·records·digest·label_state=UNREVIEWED·field_accepted=false·coverage=retained_case_rows_only를 갖는다. scope는 owner_id/profile_sha256/policy_revision/start/end이며 시작 시간 창은 start <= budget.started_at < end, 최대 24시간이다. records는 case exporter의 scope/budget/state/reason/calls/observations/spent_micros/reserved_micros에 결속한다. 별도 고정 digest로 변조와 자기 hash 교체를 거절한다.

독립 비교의 선택적 inventory 경로는 각 모델 전략의 실제 사건 집합과 inventory가 정확히 일치해야 한다. 사건 누락·중복·다른 scope·상태/예산/카운터 변경을 거절하고 원래 comparison과 CLI를 재사용한다. 기존 입력은 유지한다. 결과는 여전히 HOLD이며 보존 행 목록이 전체 관측·정상 무명령·모델 호출·재발·실제 비용·정답·현장 수용을 증명하지 않는다. 이 단계는 원장 population 선택의 누락 방지이며 signed 운영 수용을 추가하지 않는다.
