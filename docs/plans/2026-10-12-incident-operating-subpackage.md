# D-730 사건 운영 원장 책임 분리

`automation/operating`은 기존 Fleet DB의 검증된 복구 후보, 서명된 수용·폐기 epoch와 사건 단일 제출 claim을 소유한다. provider 실행은 execution, 모델 호출 예산과 원본 receipt는 ledger, 최종 CORE 호출은 기존 Fleet 제출 경로가 소유한다. 별도 서비스와 DB를 만들지 않는다.

초기 구현은 candidates 100, state 193, init 1로 294 physical lines이다. 기존 후보 구현을 이동하고 원래 import를 identity alias로 유지한다. 부모 automation에서 해당 100줄이 빠지고 alias 2줄이 남는다. 기존 부모·ledger·execution 기준과 +150 allowance는 올리지 않는다. 새로운 운영 원장 가족은 독립 검토 후 자체 SIZE_UNITS로 센다.

호출자는 기존 recovery_candidates 경로와 worker를 유지한다. 원격 SQLite CAS·경합·폐기·legacy 차단 시험, wheel/sdist의 source 없는 실제 import와 alias identity를 확인한다. 원본 독립 평가와 설치 근거를 제공하는 owner port 및 실제 제출 consumer 없이는 운영을 활성화하지 않는다. SOURCE fixture의 PASS 라벨은 현장 수용 증거가 아니다.
