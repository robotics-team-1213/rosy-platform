# Decision 숙고 책임과 사건 자동화 원장 분리

관련 계약: D-640, D-672, D-679, D-681, D-684. 최초 경계는
`2026-10-12-decision-deliberation-boundary.md`, 사건 원장은
`2026-10-12-incident-observation-budget-store.md`를 함께 따른다.

## 문제와 결정

설치된 v2 판정·프로파일, provider codec, 독립 보정 구현이 기존 숙고 단위에
함께 쌓여 실제 988줄로 성장했다. 최초 231+150 허용량을 올리지 않는다.
사용자가 승인한 책임 분리를 실제 구현 위치에 적용한다. root가 제안한 세
하위패키지 경계를 승인했고 responsibility_review가 추출·집계·설치 검증을
맡는다. 최종 구현은 root 독립 검토와 원격 GREEN 이후 통합한다.

| 책임 | 실제 소스 위치 | 소유 API와 제한 |
|---|---|---|
| 감독 | `operations/decision/src/rosy/decision/deliberation/` | Problem, opinion, Supervisor, ConditionalReview. 기존 모듈 API는 import-only 재export로 유지한다. |
| 공통 판단 계약 | `deliberation/contracts/` | ModelProfile, AdapterCapabilities, BoundProfile, Judgment, judgment/schema. 입력·근거·선택을 검증하며 provider를 호출하지 않는다. |
| provider 변환 | `deliberation/providers/` | CliProvider, VersionedCliProvider, VersionedLocalProvider, prepare_request 및 고정 argv/output codec. 명시적으로 수용된 launch port만 소비한다. |
| 독립 평가 | `deliberation/evaluation/` | CalibrationArtifact, evaluate_calibration, 지표·lineage 및 select_calibrated. immutable 입력만 계산하며 모델·DB·파일·장치·승격에 접근하지 않는다. |
| 사건 자동화 원장·관측 | `operations/fleet/fleet/incidents/automation/` | 부모/시도 예약과 기존 poll의 사건 관측. Fleet DB를 유지하고 gather·추론·CORE 명령·알림 전송을 소유하지 않는다. |

평가 source holder는 이번 단계에서 Decision 안에 유지한다. Learning part로의
소스 이전을 완료했다고 기록하지 않는다. Model PC 독립 평가 실행 입구
`tools/decision_calibration.py`는 기존 calibration API를 통해 이 pure 구현을
사용하며, 운영 inference나 평가 데이터 전송을 추가하지 않는다.

## API·의존·설치 보존

실제 구현은 새 하위패키지에 한 벌만 둔다. 기존 `profiles`, `judgment`, `cli`,
`versioned_cli`, `versioned_request`, `local`, `calibration`, `calibration_metrics`,
`calibration_selection` 경로는 명시적 import만 가진다. `_argv`, `_decode_result`
등 기존 helper와 imported public names도 같은 객체를 가리킨다. 추출 전후 아홉 실제 모듈의
non-import AST는 동일하며 import 상대 깊이만 조정한다.

기존 소비자는 그대로 연결한다: Fleet 사건 bridge/journal, AI PC Ollama broker,
site sandbox provider, offline calibration CLI, CLI/v2/profile/judgment/calibration
시험과 installed namespace probe. 주입된 launcher와 원장·claim·current-case
검사는 원래 소유자에 남는다. 새로운 service, 기본 제공자, 의무 wheel 의존,
ROS import, 장치 writer를 만들지 않는다.

`tools/packaging/fleet_sources.py`는 세 하위패키지를 기존 Fleet distribution의
`package_dirs`에 명시한다. 기존 source-root/sdist 복사는 holder 전체를 포함한다.
wheel과 격리된 sdist 설치 후 실제 하위 모듈을 양쪽 import 순서로 불러오고
기존 API와 클래스·함수 객체의 identity를 검사한다. automation은 기존 Fleet
`find_packages` 규칙으로 설치하며 원장과 관측 모듈도 installed probe에 넣는다.

## 실제 크기 집계

기존 guard의 `_rel`, `_is_prod`, `_files`, `_lines`, `_over_budget`를 그대로
사용했다. physical line에는 blank/comment를 포함하며 가장 안쪽 단위에 한 번만
집계한다. pytest는 노트북에서 실행하지 않았다.

| 단위 | 분리 후 실측 | 기존/신규 기준 | 기존 allowance |
|---|---:|---:|---:|
| Fleet 부모 | 53,408 | 기존 53,366 유지 | +150 |
| incidents 잔여 | 360 | 기존 360 유지 | +150 |
| incident automation | 322 | 신규 실제 경계 322 | +150 |
| deliberation 잔여 | 339 | 기존 231 유지 | +150 |
| 판단 contracts | 232 | 신규 실제 경계 232 | +150 |
| provider codecs | 204 | 신규 실제 경계 204 | +150 |
| pure evaluation | 275 | 신규 실제 경계 275 | +150 |

Fleet 부모와 기존 숙고·incidents 기준은 증가시키지 않는다. 새 단위는 실제
`__init__.py`를 가진 소유 패키지이며 외부 경로를 숨기거나 같은 구현을 중복
계산하지 않는다. 600/800 파일 한계, 1,000 hard tier와 +150은 변경하지 않는다.
후속 worker 또는 별도 역할 성장 전에 해당 책임과 크기를 다시 검토한다.

## 검증과 수용 경계

RED commit `1f767fcc0`: 원격 actual wheel/sdist의 새 owner import가 둘 다 실패했고
기존 size guard도 deliberation 988 및 incidents 599의 허용량 초과로 실패했다.
known-failure 비교는 NEW 3, known 0이다. 평가·provider·원장 기능은 변경하지 않았다.

첫 GREEN 요청은 CLI 시험 경로 오기로 collection exit 4여서 실행 증거가 아니다.
GREEN-2는 346 passed, 2 failed/NEW 2다. calibration facade의 기존 `wilson_lower`
export 누락은 기존 imported public names 전체를 재export해 수정했다. 다른 실패는
자식 프로세스가 `/proc/<pid>/stat` open과 read 사이에 사라져 검사 코드가
`ProcessLookupError`를 받은 것이다. 해당 시험만 `FileNotFoundError`와 동일한
프로세스 소멸로 처리하도록 고쳤고 production cleanup은 변경하지 않았다.
두 실패를 기존 known failure로 분류하거나 숨기지 않는다.

GREEN-3 source `72050909bd`: 관련 22개 시험 파일의 348개가 같은 HEAD에서
원격 AI PC(MemAvailable 9.0 GB)로 모두 통과했다. runner terminal exit 0,
known-failure NEW 0/known 0이다. actual wheel/sdist 설치, 기존 façade identity,
공통 판단·provider·calibration·CLI subprocess·원장·관측·사건 bridge·기존 replay와
전체 관련 architecture를 포함한다. 이후 실제 관측 module을 installed probe에
명시하는 설치 검증만 보강한다. 이 보강은 production source를 변경하지 않는다.

최종 설치·크기 재검사 `af28364877`: 실제 observation module까지 포함해 원격
41 passed, terminal exit 0, NEW 0/known 0을 확인했다. 이 41개는 앞선 348개와
겹치는 재검사이며 합산해 별도 시험 개수로 보고하지 않는다. 이후 변경은
이 결과 기록뿐이며 source와 test는 같은 상태다.

GREEN은 installed wheel/sdist, architecture/holder/harness, 기존 숙고·조건부 검토,
v2 profile/judgment/provider/request, calibration 및 실제 CLI subprocess,
사건 원장·관측과 bridge를 원격에서 확인한다. 최종 terminal 결과와 NEW 비교를
별도로 기록한다. SOURCE/합성 단위·설치 증거를 실제 모델 품질, 호스트 격리
admission, 제공자 활성화, Discord 발송이나 Pinky FIELD 수용으로 계산하지 않는다.
