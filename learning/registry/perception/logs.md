# perception_registry verification log

2026-10-11: D-637 folder move in progress; committed-SHA verification pending.

2026-10-11: source d4988bffba landed on local main after independent review, remote regressions/known_failures 0 NEW and installed wheel/sdist/HTTP proof. SOURCE/LOCAL GO only; CI FULL and ROS-SIM/ARM64/device/field remain unverified. See docs/validation/d637-remaining-folders-2026-10-11/result.md.

2026-10-11: D-663 의미별 eval/champion 호환과 기존 슬롯 전달 거절을 추가했다. 6353771b7 원격 intake/delivery 관련 회귀 terminal exit 0, NEW 0. strict 의미 옵션은 연구 기본값 false이며 독립 계보·표본·정답 검증과 관측 전용 도로면 전달을 완료했다는 뜻이 아니다.

2026-10-11: c90bf2d94f 엄격 intake에서 고정 학습/평가 데이터의 실제 content SHA와 학습→모델 의미를 결속했다. 원격 intake/eval/inbox 회귀 terminal exit 0, known_failures NEW 0. 3046206e88 RED는 내용 확인 API 부재와 학습 의미를 확인하지 않고 통과하던 후보를 검출했다. 독립 검수·조건별 coverage·도로면 관측 전용 전달은 미완료다.

2026-10-21: model_lineage.py가 기존 model/dataset/eval/intake 및 선택한 pointer journal을 읽는 조회를 제공한다. RED c685d9489f 13FAIL, GREEN 3d8442651d 원격 130PASS/3SKIP, NEW0. 누락된 원본·사람 검수·학습 receipt는 명시하며 운영 승인으로 올리지 않는다. 전체 브랜치 독립 계약 검토에서 지적 없음. 정본: docs/validation/pipeline-model-lineage-2026-10-21/result.md.
