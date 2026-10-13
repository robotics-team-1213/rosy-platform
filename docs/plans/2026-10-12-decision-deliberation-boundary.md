# Decision 제한 숙고 구현과 책임 경계

날짜: 2026-10-12. 결정: [D-640](../adr/D-640-fleet-deliberation-and-incident-improvement.md).
사용자의 «Discord 제외 나머지 진행» 지시로 후보 전용 소스 구현을 먼저 진행한다.
독립 현장 검수와 provider 격리 검증 전 실제 호출·운영 승격은 HOLD다.

| 책임 | 실제 소스 |
|---|---|
| 입력·근거·의견 검증, 전체 시간/횟수/비용 제한, 비개입 zero-call | `operations/decision/src/rosy/decision/deliberation/__init__.py` |
| 고정 argv와 구조화 출력 번역 | 같은 패키지 `cli.py` |
| 사건·세대별 durable 시작/의견/종료, 재시작·중복 fence | `operations/fleet/fleet/server/deliberation_journal.py` |
| 같은 정답 세트의 규칙/단일 모델/숙고 비교 | 기존 `tools/decision_replay.py` |

Decision은 모델 의견만 만들고 Fleet은 기존 DB의 별도 원장 테이블을 소유한다.
CORE/OMX 실행 권한·기존 Mission 원장·알림 outbox는 그대로 각 소유자에 있다.
새 서비스·DB 서비스·평가 holder·범용 framework를 만들지 않는다.
현재 Fleet worker/HTTP에 실제 모델 호출을 자동 연결하지 않는다. trusted caller가
`DeliberationJournal.run`에 현재 사건 검사와 supervisor를 주입하는 후보 전용 진입점이다.

실제 Python 하위 패키지를 P6 단위 `decision/src/rosy/decision/deliberation`로 등록한다.
독립 검토자 `responsibility_review`가 경계 적합성을 확인했다. 같은 변경에서 측정한
하위 단위 231줄과 부모 Fleet 52019줄을 기록하며 기존 +150·파일 제한과
observe/server/UI 추출 의무를 유지한다. Fleet의 새 86줄 원장은 부모에 남는다.
다음 성장은 의견/CLI 책임 안에서 재검토하며 저장·명령 권한을 가져오지 않는다.

최신 main `a78d1f2ea7`의 D-664 작업 현황을 통합하면 Fleet 부모는 52236줄이며
Decision 하위 단위는 231줄 그대로다. D-664의 읽기 projection·Task/Mission owner와
기존 camera/auth/trip·observe/server/UI 조건도 합친 판정에 보존한다.

이후 main `5f4040f306`의 D-655 지도 없는 survey/recording/UI를 통합한 부모는
53093줄, 하위 단위는 231줄이다. 기존 survey World 신선도/녹화 연속성,
Fleet teach recording/CAS, UI draft·camera import 소유와 크기 조건을 모두 보존한다.

Fleet 배포는 `tools/packaging/fleet_sources.py`의 명시 하위 패키지 mapping을 사용한다.
직접 호출자는 원장·테스트·기존 offline replay CLI이며 예전 경로 shim은 없다.
설치 wheel/sdist 양쪽에서 Decision 하위 패키지와 Fleet 원장 import를 확인한다.

원격 fake 계약·설치 43건은 source `150c3e0f3d`에서 통과했고 known failures NEW0다.
정상 비개입, 상충, stale/세대 변경, unknown 비용, 학습 녹화 누출, 고정 검수 profile,
원장 장애/재시작을 포함한다. source 검사는 실제 모델 품질이나 격리 증명이 아니다.

offline CLI는 다음 기존 도구를 사용한다. cases/runs는 JSON 배열이고 입력 파일은
비공개 검수 자료를 둔 X 세션에서 관리한다. 실제 모델을 호출하지 않는다.

```powershell
python tools/decision_replay.py <cases.json> --comparison-runs <runs.json> --reviewed-profile <profile.json> --training-manifest <training.json>
```

case: `id, session_id, recording_id, problem_hash, expected, reviewed_by`.
run: `case_id, problem_hash, mode, choice, latency_ms, cost_usd, forbidden_effect,
binding_error, profile_revision, policy_revision`. mode는 rules/single/deliberation이다.
profile은 `dataset_sha256, limits, reviewed_by, minimum_cases, revisions`를 평가 전에
검수한다. revisions의 각 mode는 `profile_revision, policy_revision`을 고정한다.
limits는 `error_rate, p95_latency_ms, cost_usd`이며 manifest는 `sessions, recordings`다.
dataset hash는 cases를 `json.dumps(cases, sort_keys=True, allow_nan=False)`로 직렬화한
UTF-8 SHA256이다. 한 평가 세트에서 recording ID는 전역 유일해야 한다.
첫 버전은 동일 녹화에서 여러 시점을 독립 표본으로 세지 않는 보수적인 경계다.
학습/평가 녹화의 이름 변경·유사 프레임은 별도 사람 lineage 검수 대상이며 ID 검사만으로
자동 탐지했다고 주장하지 않는다. PASS_OFFLINE_ONLY도 FIELD 승격을 허용하지 않는다.

모델 PC에서 읽기 전용으로 Claude Code 2.1.287와 OpenCode v2.0.22의 help/version을 확인했다.
CLI 번역은 fake 출력으로만 검증했다. 실제 GLM provider ID·인증 프로파일·OS 격리·
OpenCode 토큰/비용 상한·프로세스 취소와 실제 JSON envelope는 미확인이다.
`CliProvider`는 검증된 isolated launcher 없이는 생성되지 않으며 기본 활성화 경로도 없다.
Claude의 비용 flag는 추정 비용 상한이므로 실제 비용 보장을 대신하지 않는다.
근거: [Claude CLI](https://code.claude.com/docs/en/cli-reference),
[비대화 실행](https://code.claude.com/docs/en/headless),
[OpenCode CLI](https://opencode.ai/docs/cli/),
[권한](https://opencode.ai/docs/permissions/).

다음 순서: source 독립 검토·구조/회귀 원격 검사 → 승인된 로컬 FF →
팀의 Pinky 정답·한계 확정 → 격리 프로파일/실제 provider smoke →
동일 세트 offline 비교 → 출력 미적용 shadow → 제한 장치·FIELD 검수.
Discord는 이번 범위에서 제외하며 push·배포·실제 모델 호출·주행은 수행하지 않는다.
