# 사건 원장과 관측·모델 생명주기 책임 분리

관련 계약: D-681, D-684. 기존 책임 기록은
`2026-10-12-deliberation-role-subpackages.md`,
`2026-10-12-incident-observation-budget-store.md`,
`2026-10-12-incident-case-worker.md`를 함께 따른다.

## 문제와 구현 경계

사용자가 승인한 책임 분리를 D-684 사건 worker까지 적용한다. 원장·관측을
함께 세던 automation이 783줄로 성장하여 기존 322+150 한도를 넘었다.
기준이나 허용량을 올리지 않고 실제 SQLite 원장 구현을 별도 ledger 책임으로
옮긴다. 부모의 상태·호출·비용·재시작·종결·FINAL 전달 원장은 같은 Fleet DB에
한 벌만 남는다. 책임 분리와 구현은 responsibility_review가 담당하고 root가
최종 source와 설치 검증을 독립 검토한다.

| 책임 | 실제 소스 | 경계 |
|---|---|---|
| 원장 입력·영수증 | `automation/ledger/contract.py` | CaseScope, CaseBudget, 비용 단위와 제한된 summary 검증. |
| 트랜잭션 원장 | `automation/ledger/store.py` | 부모·원본 revision·creator·시도·역할별/전체 예산·관측 종결 기록·FINAL pending/ACK. provider·gather·장치 명령·알림 전송 없음. |
| 현재 관측 | `automation/observation.py` | 기존 poll의 immutable 사건 읽기. 새 gather나 CORE 호출 없음. |
| 관측 종결 | `automation/closure.py` | 원래 episode의 clear 전이와 이후 fresh normal CORE 관측을 대조. 모델 선언이나 Action 성공을 대체하지 않음. |
| 모델 생명주기 | `automation/worker.py` | 주입된 수용·현재 profile·사람 소유·예산·provider·FINAL 포트와 취소·deadline. 기본 비활성, 선택은 advisory. |
| 팀 전달 | `incidents/notifications.py`, `incidents/final_review.py` | 원장에 묶인 read-only 실패 진단과 기존 고정 채널 outbox. 판단·실행 권한 없음. |

CaseStore 본문과 DB schema·전이·예산 수치는 바꾸지 않는다. contract 본문은
동일하다. store 내부 ObservedClosure import만 새 깊이에 맞춰 `..closure`로
바꾼다. 원본 revision, creator 기록과 caller-owned transaction, 외부 worker의
진행 중 시도 차단, 비용 UNKNOWN, pending FINAL/ACK를 그대로 유지한다.

## API와 실제 설치

기존 `automation.contract`, `automation.store`는 명시적 import만 가진다.
클래스·함수·기존 imported globals가 새 구현과 같은 객체를 가리킨다.
worker·closure·final_review의 exact CaseScope 타입 검사도 같은 클래스를 쓴다.
기존 소스 호출자는 그대로 연결한다: worker·종결·FINAL 알림, 읽기 전용
`tools/incident_model_feedback.py`, 원장·worker·알림·feedback 시험.

Fleet의 기존 `find_packages(exclude=['test'])`가 ledger를 발견한다. 새 배포물,
필수 dependency 또는 native payload 소비자를 추가하지 않는다. wheel과 sdist를
실제 설치한 뒤 소스 checkout을 격리하고 두 import 순서에서 ledger·worker·closure를
불러온다. 모든 이전 globals의 객체 identity와 typed closure 소비자도 검사한다.
Decision의 세 실제 책임 패키지와 기존 native no-clobber 검사도 유지한다.

## 실제 크기와 유지하는 기준

`test_module_structure.py`의 기존 `_files`, `_is_prod`, `_rel`, `_lines`와
innermost unit 판정을 AST로 읽어 stdlib만 실행했다. 노트북 pytest는 실행하지
않았다. 주석·빈 줄을 포함하는 같은 physical-line 규칙을 사용한다.

| 단위 | 실제 줄 | 기준 | 허용량 |
|---|---:|---:|---:|
| Fleet 부모 | 53408 | 53366 유지 | +150 유지 |
| incidents, automation 제외 | 502 | 360 유지 | +150 유지 |
| automation, ledger 제외 | 429 | 322 유지 | +150 유지 |
| ledger 실제 구현 | 370 | 370 신규 책임 판정 | +150 유지 |
| Decision 숙고 나머지 | 339 | 231 유지 | +150 유지 |

ledger는 contract 82 + store 287 + 실제 package init 1줄이다. automation의
429줄은 init 1 + closure 46 + observation 81 + worker 286 + 기존 경로의
import facade 7/8줄이다. 새 ledger를 부모나 incidents에서 다시 차감하지 않는다.
추출이 크기를 줄인 대상으로 기록되는 단위는 automation이다. 파일의 600/800
기준과 HARD_TIER도 유지한다. 새 원장 계열이 커지면 실제 책임 검토를 다시 한다.

## 검증과 수용 경계

통합 시작점은 root의 `fb6330f3f`다. worker 원격 통합 161 passed/NEW 0,
creator 취소 및 외부 in-flight 차단 증거는 담당 worker plan에 기록되어 있다.
이전 component와 중복이므로 합산하지 않는다.

설치 회귀를 먼저 추가한 `1fa9ab9fa`에서 실제 wheel/sdist 두 경로의 ledger
부재와 automation 크기 초과를 원격 RED로 확인했다. AI PC 9 GB 기준을
충족했고 terminal exit 1, known-failures 3 NEW였다. 이 실패를 기존 실패
목록에 넣지 않는다. 추출 후 같은 실제 설치·크기 검사와 원장·worker·FINAL·
feedback 영향군의 원격 GREEN을 확인한 뒤 완료 증거를 이 문서에 기록한다.

첫 GREEN 후보 `c17eb326c`는 Site PC 8.9 GB/3.4 cores 기준을 충족했으나
terminal exit 1, known-failures 2 NEW였다. 두 실패 모두 같은 Fleet index의
생성 기록 누락이었다. 로그 제목을 source SHA 형식으로 고친 뒤 generate를
하지 않아 최신 원장 책임 기록이 index에 빠졌다. 설치·size·원장·worker·FINAL·
feedback 검사에는 실패가 없었다. 원래 generator가 해당 최근 기록 행만
갱신했으며, 이를 커밋한 뒤 같은 15파일을 다시 검증한다. 기존 실패 목록은
바꾸지 않는다.

생성 기록을 고친 `cc19ce9ef`의 동일 15파일 원격 GREEN2는 Model PC 9 GB
자원 기준을 충족하여 390 passed, terminal exit 0, known-failures NEW 0을
확인했다. lint는 errors 0과 기존 last_verified warnings 28건이었다.
root의 독립 통합 착지 검사는 AI PC 9 GB에서 실제 설치·기존 resolver loop를
포함한 15파일 375 passed, NEW 0으로 종료하여 `819a6e3140`으로 로컬 main에
착지했다. 서로 다른 영향군과 반복 시험의 수를 합산하지 않는다.
통합 로그는 `X:/DevTemp/projects/rosy-platform/2026-10-12--033443--deliberation-local-gateway--fc42b3/logs/worker-ledger-land/feat-conditional-model-review/run-1-1.txt`다.

이 변경은 소스·설치 책임 분리다. 운영 활성화·provider 실제 호출·배포·push·
독립 보정 품질·물리 장치 수용은 입증하지 않는다. CORE 최종 명령, 사람 인수,
모델 실행 admission과 새로운 평가 데이터 승격은 기존 관문에 남는다.
