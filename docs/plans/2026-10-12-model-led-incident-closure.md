# 모델 주도 범용 관제·사건 종결 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 교체 가능한 여러 판정 모델이 사건을 판단·해결·확인·개선하고 사람은 최종 미해결 사건을 검토한다.

**Architecture:** Fleet은 사건·근거·원장과 실행 연결, Decision은 판정·비교·단계 선택, AI PC는 운영 추론, Model PC는 독립 평가를 담당한다. CORE의 안전 권한과 기존 공통 tool catalog/admission을 재사용한다. D-679의 한 번의 연결 시험 이후 독립 수용된 프로파일로 자동 처리를 확대한다.

**Tech Stack:** 기존 Python Decision/Fleet, SQLite journal/outbox, 공통 model tool contract/catalog, Qwen 로컬 추론, OpenCode GLM, 모델별 고정 어댑터, 독립 replay/evaluation.

---

## 통합 요구사항

2026-10-12 사용자 재확인: 이 문서와 활성 목표는 지금까지의 요구사항을 하나로 묶는다. 최종 목표는 범용 사건의 **판단 → 조건부 재평가 → 제한된 처리 → 결과 확인 → 최종 미해결 인수 → 실패 피드백 → 독립 평가 → 승격·복귀**다. 사람이 매 단계 승인하는 흐름 대신 승인된 범위에서는 모델이 처리하고 사람은 최종 문제와 평가 정답·한계를 검수한다. 첫 현장 대상은 Pinky 차선 정지·재관측이며 이후 문제 유형은 각자의 근거·행동·성공 계약을 수용한 뒤 확대한다.

### 현재 시작점과 다음 순서

D-727은 `32798ee0be`로 로컬 main에 착지했다. 마지막 적격 AI PC/Model PC 원격 두 그룹은 합계 6,255 passed/313 skipped/NEW 0 및 lint다. 고정 로그는 세션 `logs/operational-receipt-land-32798ee0be-{1,2}.txt`다. 공통 서명 계약과 설치 소비자 검증까지의 source 완료이며 운영 품질 수용은 아니다. 다음은 actual 평가 원본·한계·truth·coverage의 독립 재검증, 같은 Fleet DB의 수용/폐기 epoch, 사건당 단일 physical claim, 기존 loop의 rule/model 소비 및 실제 결과 연결이다. FULL CI·실제 모델·배포·현장 수용은 별도이며 목표는 ACTIVE다.

D-724는 `e8d27b00b3`로 로컬 main에 착지했고 마지막 적격 AI PC 원격 통합은 5,558 passed/282 skipped/NEW 0 및 lint다. 고정 로그는 세션 `logs/stuck-final-guard-land-e8d27b00b3.txt`다. D-727은 공통 운영 수용/폐기 서명·현재 owner binding/epoch/기간을 검증하는 SDK 0.1.11과 Fleet 0.1.3 floor·local execution 0.1.5·CI pin을 구현한 브랜치 작업이다. 초기 계약/설치/구조 99개와 source-less wheel/sdist HMAC·UTF-8·CI/문서 회귀 144개는 적격 원격 PC에서 terminal exit 0/NEW 0이며 독립 SOURCE 검토를 승인받았다. actual evaluation 원본이 HOLD이면 signed reviewed 메타도 importer가 거절해야 한다. 운영 품질·같은 DB 수용/폐기 상태·단일 claim·모델/현장 결과는 다음 구현이며 전체 목표는 ACTIVE다.

D-722는 `c55c64e5d4`로 로컬 main에 착지했다. 마지막 적격 Model PC 원격 통합은 5,656 passed/282 skipped/NEW 0 및 lint이며 고정 로그는 세션 `logs/model-recovery-land-c55c64e5d4.txt`다. 후보는 비실행 기록이며 실제 운영 수용·단일 물리 claim·Fleet 제출 연결·모델/현장 결과는 남아 있다. 후속 D-724는 지원 확인 GET 뒤 POST 직전에 최종 검증 포트를 두는 소스 구현이며 관련 원격 회귀 123개, 실제 wheel/sdist 설치·문서 계약 104개는 terminal exit 0/NEW 0이다. D-724 병합은 아직 미확인이다. GLM 관리자 준비 스크립트는 존재하지만 새 설치 경로는 현재 없다. 목표는 ACTIVE이고 실제 호출은 하지 않았다.

현재 실행 중인 D-722는 모델 복구 후보를 실제 완료된 시도와 기존 사건 DB에 결속한다. 첫 보강은 assessment revision과 CORE 관측 seq/timestamp의 일치, 후보 조회의 원본 receipt·전체 내용 재검증, 종료 시 진행 중 DB 작업의 완료 대기다. 후보 저장은 `automation/recovery_candidates.py`, 모델 호출은 기존 `automation/execution/worker.py`가 소유한다. 기존 크기 한도를 유지하며 이 후보는 실행 권한을 부여하지 않는다. 이후 D-716의 단일 rule/model 소비·운영 수용·결과 확인을 연결한다.

첫 보강 `338fa3aa68`은 실제 worker·SQLite·관측 시점·종료 대기와 구조 회귀 104개, 판정·tool catalog·기존 패키지 설치·문서 계약 회귀 258개를 적격 원격 AI PC에서 terminal exit 0/NEW 0으로 확인했다. lint는 0 errors다. 이 시점에는 브랜치 구현이며 로컬 main 병합·후보 모듈 자체의 wheel/sdist 설치·실제 모델·현장 결과는 아직 확인하지 않았다.

D-718은 `f7221c12e6`로 로컬 main에 착지했다. main 변경을 반영해 두 번 통합했으며 마지막 적격 AI PC/Model PC 원격 세 그룹은 합계 18,671 passed/822 skipped/NEW 0 및 lint를 통과했다. 고정 로그는 세션 `logs/stuck-condition-land-f7221c12e6-{1,2,3}.txt`다. API/제어기의 혼합 설치 지원 검사, SDK 의존성·실제 wheel/sdist, 기본 요청 호환성과 CORE 조건부 거절을 포함한다. FULL CI는 착지 도구가 별도로 요구하며 push·배포·실제 모델·현장 수용은 미확인이다. 다음은 typed 물리 후보 원장과 규칙/모델 단일 소비, signed 운영 수용·최종 폐기 재검사와 실제 결과 연결이다. 목표는 ACTIVE다.

D-718 source checkpoint는 [CORE 조건부 막힘 답](../adr/D-718-conditional-core-stuck-answer.md)과 [물리 처리 연결 계획](2026-10-12-model-led-bounded-incident-recovery.md)에 기록한다. 조회 이후 사람 WAIT·CORE local fallback·시도 변경을 실제 적용 시점에 거절하고, 부분 업그레이드에서 조건이 무시되는 제출을 차단했다. SDK/API/Fleet와 실행 의존 소비자의 버전·offline installer·CI pin을 함께 갱신했으며 독립 SOURCE 안전 검토와 수정 후 설치 closure 회귀를 확인했다. 다음은 모델의 typed 물리 후보를 사건 원장에 고정하고 기존 loop 한 곳이 규칙/모델 중 하나만 소비하는 연결이다. 전체 목표는 ACTIVE이며 source의 조건부 API가 모델 운영 수용·현장 성공을 뜻하지 않는다.

현재 통합 목표는 **모델 주도 범용 사건 해결·자체 개선**이며 기존 ACTIVE 목표를 이어간다. 책임은 Fleet의 사건/원장/단일 제출, Decision의 구조화 판단/조건부 검토, AI PC의 설치된 운영 추론, Model PC의 정답/보정/독립 평가, CORE와 각 장치 owner의 최종 실행으로 나눈다. 소스 저장소의 위치와 실제 실행 호스트는 별도 설치 계약으로 확인한다.

| 다음 실행 묶음 | 핵심 완료 기준 |
|---|---|
| CORE 중복 복구 차단 | console/local 복구 진행 중 늦은 답이 타이머·시도 수를 재시작하지 않음; 기존 WAIT/ABORT 보존 |
| [D-716 물리 처리 연결](2026-10-12-model-led-bounded-incident-recovery.md) | 단일 rule/model 소비, bounded 대기, CORE 적용 시점 사건/phase 확인, signed 운영 수용·폐기 재검사 |
| 독립 수용·설치·결과 확인 | 전체 기록 창과 검수 정답/한계 결속, 고정 runtime readback, 접수와 실제 해결 구분 |
| 범용 backend와 개선 | door/arm 고유 실행 owner 연결; 실패 검수→독립 비교→새 사건 승격/복귀; Jev/Laya 역할 교체 |

Qwen이 기본 판단을 맡고 Fleet과의 불일치·응답 문제에는 OpenCode의 기존 GLM 연결로 제한 재평가한다. 정상 사건은 모델 호출·조치 없이 끝내고, 해결 범위를 벗어난 최종 사건만 팀 인수로 남긴다. Discord 실제 작업은 담당 세션이 계속한다. 자기 보고 확률을 자동 처리 근거로 채택하지 않으며 독립 보정·운영 수용과 결과 확인을 함께 요구한다.

D-715는 `ca1dae7902`로 로컬 main에 착지했고 적격 원격 통합은 596 passed/skipped 0/NEW 0 및 lint를 확인했다. 아래 checkpoint들은 당시 증거의 이력이다. D-716은 Proposed이고 실제 조치 연결·운영 수용·배포·현장 검증은 미완료다.

최신 D-715 source checkpoint는 읽기 전용 원장 사건 inventory와 별도 고정 digest를 실제 독립 비교/CLI에 연결한 것이다. 평가에서 실패 사건을 누락하거나 같은 사건의 다른 snapshot으로 덮는 경우를 거절한다. `871591c3e6`의 관련 원격 회귀 및 `9baec27cfb`의 population/실제 CLI 추가 12개 회귀는 terminal exit 0/NEW 0이고 독립 검토를 통과했다. retained_case_rows_only 목록을 전체 정상 명령·모델 호출·재발·정답 coverage로 해석하지 않으며 승격은 HOLD다. D-714는 `e78eca89e3`로 로컬 main에 착지했고 원격 main 통합 378 passed/skipped 0/NEW 0이다. 다음은 population과 원본의 완전한 관측/명령/결과 창 및 독립 정답·한계를 결속하는 것이다. 실제 배포·모델·현장 수용은 미완료이며 목표는 ACTIVE다.

최신 D-714 source checkpoint: 별도 배포 고정 SHA와 전체 profile set을 설치한 provider/config에 결속하는 root 로더를 `4301911968`에서 구현했다. 실제 factory/dispatcher 연결·재로드·변조/미설치 ID/revision/예산 거절과 malformed JSON 오류 비노출을 적격 원격 회귀 terminal exit 0/NEW 0 및 독립 검토로 확인했다. 자동 제공자 생성·호출·권한 확대는 없다. D-706~D-713은 `3a9f812bd222`로 로컬 main에 착지했고 두 원격 통합 그룹 합계 6,312 passed/295 skipped/NEW 0이다. FULL CI와 실제 배포/모델/현장 증거는 별도이며, 다음은 운영 coverage·독립 수용 receipt와 실제 설치/readback·현장 처리의 결속이다. 전체 목표는 ACTIVE다.

최신 D-713 source checkpoint는 기존 Fleet loop/outbox의 단일 pinned worker dispatcher와 실제 root 승인 포트 구성이다. 기존 사건의 모델·예산·UNKNOWN은 유지하고 현재 선택의 설치 worker만 새 사건을 생성하며 정상 상태는 호출하지 않는다. `799587b251`의 실제 원장→root→create_app→dispatcher·승인 폐기/제한 reviewer·설치/구조 원격 회귀는 terminal exit 0/NEW 0이다. shutdown의 실제 RED 결함을 수정하고 모든 worker 정리를 기다린 뒤 오류를 보고한다. 상세는 [프로파일 lifecycle 계획](2026-10-12-reasoning-profile-lifecycle.md)의 D-713을 따른다. 통합 병합은 D-692 stale gap lint 오류를 수정해 다시 진행하며, 다음 source 작업은 signed 운영 수용과 실제 설치 loader/readback·운영 coverage 연결이다. source의 모델 분배를 실제 모델 품질·현장 성공으로 대신하지 않는다.

최신 D-712 checkpoint는 `d0541c3b27`의 영속 local current/previous 선택·revision CAS/복귀와 같은 DB의 원자적 사건 배정이다. 실제 receipt/poll·create_app, 동시 전환·재시작·기존 scope/예산 보존과 설치·크기 회귀는 적격 Model PC에서 terminal exit 0/NEW 0이다. 선택·복귀 책임은 기존 automation/routing에 두고 ledger 허용량을 올리지 않았다. 다음은 설치·승인된 프로파일과 pinned worker dispatcher 연결이다. 이 local 선택을 모델 품질 수용·운영 승격으로 해석하지 않는다.

D-705는 `99e96cd190a0fae123a3dcb5ff52a1a0526e1121`로 로컬 main에 착지했다. main이 이동해 기존 도구의 merge→회귀를 다섯 번 수행했고 마지막 실제 AI PC 통합은 12,035 passed/1,265 skipped/NEW 0, terminal exit 0이다. 고정 로그는 세션 `logs/incident-calibration-land-ae594b.txt`, SHA256 `0caf1d81579e267ed62a1f129b2def4a01b5c1a466fee180bc7ddf80601aa5a3`다. push·CI·배포·실제 모델·현장 증거가 아니며 D-706 이후 작업은 아직 main에 착지하지 않았다. 아래 이전 시작점의 진행 중 표현은 당시 상태다.

2026-10-12 최신 시작점: 통합 목표는 ACTIVE이며 기존 목표·ADR·진행 증거를 초기화하지 않는다. D-706 후보 생산, D-707 영속 보정 승인, D-709 실제 Fleet 판단 포트 연결, D-710 사건 소유권 분리와 D-711 새 사건 생성 허가 분리까지 source checkpoint를 확보했다. D-711의 `31f2cbbe8f`는 적격 AI PC 원격 시험 112 passed/terminal exit 0/NEW 0이며 독립 source 검토에 중요한 blocker가 없었다. 상세와 증거는 [프로파일 lifecycle 계획](2026-10-12-reasoning-profile-lifecycle.md)을 따른다.

바로 다음 구현은 **영속 current/previous 전환과 원자적 사건 배정 → 사건에 고정된 worker dispatch → 복귀·재시작 readback**이다. 로컬 생성 허가와 사건 생성 사이에 current revision이 바뀌는 경쟁을 실제 SQLite 시험으로 먼저 재현한다. 이어 같은 트랜잭션에서 사건 소유 revision을 고정하고, 기존 사건의 예산·시도·UNKNOWN을 보존한다. 아래 D-705 시작점과 이전 source 감사는 당시 기록이며 최신 완료 범위를 대신하지 않는다. D-705 로컬 착지 검증은 진행 중이고 D-706 이후 변경의 main 통합·배포·현장 수용은 미완료다.

2026-10-12 통합 목표 재확인: 기존 ACTIVE 목표와 진행 증거를 보존하고 아래 순서로 계속한다. 현재 D-705 작업은 실제 worker 실행 책임 분리와 외부 승인 hash/보정 포트 연결이다. 정상 입력은 모델 호출 없이 유지하고, 미수용 보정에서는 같은 입력의 primary 판정을 제한 reviewer에 전달한다. GLM 실제 입력 codec의 불일치 전제와 승인 포트 예외 처리, 설치 공개 import를 회귀로 확인한다. 영속 승인 공급·사건별 revision 전환·물리 조치·현장 성공은 이 단계의 완료 범위가 아니다.

| 통합 목표의 남은 실행 순서 | 완료 판단 |
|---|---|
| 운영 보정 gate와 설치 호환성 | 실제 worker·GLM codec·wheel/sdist 원격 회귀, 독립 검토, 승인된 로컬 착지 |
| 영속 reasoning 원장과 프로파일 교체 | candidate/current/previous 승인 hash, CAS·재시작·복귀; 기존 사건 revision 보존 |
| 범용 처리·결과 연결 | Pinky부터 domain별 근거·허용 조치·성공 확인을 연결하고 CORE가 최종 admission |
| 최종 인수·피드백·독립 평가 | 정상 미개입·누락·위험·다른 사건 조치·불필요 명령·재발·지연·비용의 실제 증거 |
| 제한 토론과 개선 수용 | Qwen 기본, GLM 조건부, Jev/Laya 교체; 독립 기준 통과 후 새 사건에만 적용·복귀 |

Discord 실제 설정·발송은 담당 세션이 진행한다. 모델의 자기 보고 확률만으로 자동 처리 범위를 늘리지 않고 독립 보정·기존 안전/호출 예산·결과 readback을 함께 확인한다. 사람은 최종 미해결 사건과 평가 정답·한계를 검수한다.

전체 source 감사(`6a73839f03`)에서 외부 설치·현장 검증 외의 미구현 연결도 확인했다. `select_calibrated`는 production worker가 호출하지 않고 영속 reasoning candidate/current/previous 및 승격/복귀 loader가 없다. global profile 변경으로 기존 사건을 HOLD하는 fence는 새 사건만 교체하는 전환이 아니다. worker는 line_follow/read-only만 연결되어 있고 물리 처리·door/arm backend는 미구현이다. 다음은 [판정 프로파일 lifecycle](2026-10-12-reasoning-profile-lifecycle.md)의 기존 registry 소유자 reasoning 계약·전환 → Fleet 승인 hash/보정 gate → 사건별 revision 보존·복귀다. 전체 운영 coverage·자동 실패 분류/검수 label 수용/training도 남아 있다. 이전 source checkpoint는 각 부분의 증거이며 전체 source나 목표 완료가 아니다.

D-704는 commit `5f06e03ab1d2a2d870e341c1801259605857552d`로 로컬 main에 착지했다. 여섯 축의 비정상 숫자와 네 비평면 축의 움직임을 버리지 않고 거절하는 Pinky 최종 속도 원본 검증이다. Native CDR/MCAP RED 22 NEW를 재현한 뒤 적격 Model PC의 원본 검증 전용 환경에서 main 통합 473 passed/skipped 0/NEW 0과 lint를 확인했다. 전체 Pinky/구조 107개 회귀와 고정 로그는 [최종 속도 원본 계획](2026-10-12-pinky-final-velocity-evidence-boundary.md)에 있다. 공유 CI venv나 장치 runtime을 바꾸지 않았다. 정상 주행 속도와 불필요 모델 개입은 다른 개념이며 전체 명령/재발 coverage는 여전히 미확인이다. GLM 관리자 설치 readback을 기다리며 전체 목표는 ACTIVE다.

실제 V2 런타임 readback: AI PC의 기존 전용 venv에서 입력 검증·자식 import를 모델/네트워크 호출 없이 확인했고, 별도 metadata 1회로 고정 Qwen resident 조건을 확인했다. 소비된 Qwen V2 표식은 유지하며 이전 실패 원인과 실제 응답은 미확인이다. GLM frozen V2 설치 디렉터리가 아직 없고 sudo password가 필요해 관리자 OpenSSH 준비 명령의 실제 실행/readback을 요청했다. 이 준비는 모델 호출·credential importer를 포함하지 않는다. [실제 readback](../validation/deliberation-host-admission-2026-10-12/local-qwen-smoke.md)의 V2 절을 따른다. 기존 구버전 transport 성공·최신 source 병합·V2 runtime·독립 품질을 혼용하지 않으며 전체 목표는 ACTIVE다.

D-703은 commit `70cff59396a5338346ff6c65e3b7a836d99632e0`로 로컬 main에 착지했다. 실제 model export의 prediction과 별도 검수 정답·오류·지연을 기존 보정/동일 정답 비교 CLI에 결속한다. 개인 profile hash와 receipt·case·attempt·input·generation을 확인하고 원장 밖 확률·UNKNOWN/누락 보간·외부 검수 dataset hash 자동 변경을 거절한다. 적격 Model PC 8.1GB의 관련 main 통합 원격 시험은 569 passed/NEW 0과 lint를 통과했으며 독립 검토 지적을 수정했다. [검수 입력 결속 계획](2026-10-12-reviewed-feedback-calibration-binding.md)에 고정 로그와 통합 전 127개 회귀를 기록했다. 다음은 실제 검수 자료·지연 원본·출처의 수용과 운영 coverage 연결이다. 사람 표시 이름이나 선언된 source hash만으로 진위를 입증하지 않는다. 실제 모델·배포·현장·승격/복귀는 미완료이며 전체 목표는 ACTIVE다.

D-702 보정 기준 보완은 commit `d34e8c2e358129143dd9933b2ace33f42558aafb`로 로컬 main에 착지했다. 기존 독립 확률 보정 계산의 PASS에도 검수된 `minimum_bin_cases`를 적용하고 네 가지 금지 오류 건수를 보고한다. 적격 AI PC 9GB의 Fleet 전체·제공자·설치·구조·release 통합은 5,039 passed/246 skipped, terminal exit 0, NEW 0과 lint를 통과했고 독립 검토에서 중요한 blocker는 없었다. [구간 표본 수 계획](2026-10-12-independent-calibration-bin-support.md)에 고정 로그와 통합 전 110개 회귀 근거를 기록했다. 실제 원장·별도 검수 정답·latency와 source lineage를 결속하는 평가 입력 생산은 다음 작업이다. 없는 정답·지연·coverage를 추정하지 않으며 실제 모델·배포·현장 수용·승격/복귀는 미완료이고 전체 목표는 ACTIVE다.

최신 D-701 source checkpoint: commit `410d69f8e72ed223fcfba9f52982c8df4bd34294`로 실제 규칙 선택의 읽기 전용 export와 독립 cohort /2 비교를 로컬 main에 착지했다. 기존 /1·단독 primary /3과 동일 사건·hash·scope·split 검증을 유지한다. 적격 AI PC 9GB의 관련 26개 파일 원격 통합 시험 667 passed, terminal exit 0, known-failures NEW 0과 lint를 확인했다. 독립 검토의 전체 JSON 크기·실제 CLI 연결 지적도 수정했다. 고정 로그는 세션 `logs/rule-export-land-410d69f8e7/run-1.txt`다. 상세는 [독립 규칙 export 계획](2026-10-12-independent-rule-export.md)을 따른다.

다음은 독립 정답·수용 한계와 정상 무명령·모델 호출·재발의 완전한 기록 범위다. 규칙 선택만으로 운영 성공이나 0건을 주장하지 않으며 실제 모델·배포·현장 수용·승격/복귀는 미완료다. 통합 목표는 ACTIVE다. 아래 D-700 checkpoint는 이전 단계의 증거다.

최신 D-700 source checkpoint: commit `8520b77d663e1922f68518821ed771ad4d080d5e`로 실제 resolver 반환·Assessment·roster/config hash의 선택 원장과 현재 baseline 포트를 로컬 main에 착지했다. normal/ABSTAIN·NONE/ANSWER/HOLD/HANDOFF·RULE_ONLY/MIXED를 보존하며 physical WAIT를 human으로 해석하지 않는다. claim·stale·사건/revision·rule config 변경과 기록 실패에서 비교 기준을 거절한다. factory의 기본 포트가 실제 선택을 worker Problem.fleet_choice로 연결하며 기존 명시적 포트는 유지한다.

적격 AI PC 9GB에서 최신 main 통합의 12개 시험 그룹 621 passed/1 skipped, terminal exit 0, known-failures NEW 0과 lint를 확인했다. 실제 wheel·sdist SDK 위치·기본 resolver 생성과 local execution 계약 호환, 기존 resolver/worker와 구조 회귀를 포함한다. 독립 검토의 설치/WAIT 문제를 수정하고 SDK 0.1.10·Fleet 필수 의존성·CI/local pin을 동기화했다. 고정 로그는 세션 `logs/rule-land-8520b77d66/run-1.txt`, SHA256 `e0d75ec886a2ff32916deab02ef4106ad5678f3b5e5a00f881697d724f47b557`다.

다음은 [규칙 근거 계획](2026-10-12-fleet-rule-selection-evidence.md)의 실제 원장 export와 D-697 독립 cohort 소비다. 선택 원장은 실행·성공·모델 호출 0건·정상 무명령·재발 0건과 같은 의미가 아니다. map/lifecycle 전체 provenance·독립 정답/한계·승격/복귀·실제 모델·전체 CI·배포·현장 수용은 미완료다. 전체 목표는 ACTIVE이며 아래 D-699 checkpoint는 이전 단계의 증거다.

#### 이번 목표의 실행 기준

활성 목표를 유지하며 새 목표로 기존 진행을 초기화하지 않는다. 사용자가 지정한 순서는 **소유자 확인 → 모델 원장 도구 분리 → 작업 규칙 추출 → 중앙 판단·결과 연결 → 알림·사람 인수 → 독립 평가 → 제한 모델 토론·개선**이다. 아래 checkpoint의 source 완료와 실제 운영 완료를 구분하고, 미완료 범위는 다음 검증 작업으로 남긴다.

| 단계 | 현재 책임·산출물 | 다음 검증과 완료 조건 |
|---|---|---|
| 소유자 확인 | Fleet 사건·원장·admission, Decision 판단, AI PC 운영 추론, Model PC 독립 평가, CORE 최종 제어 | 실제 설치 묶음·서비스 설정·실행 revision을 읽어 확인한다. Model PC 평가와 AI PC 운영 추론을 소스 폴더 이름으로 혼동하지 않는다. |
| 모델 원장 도구 분리 | 기존 역할 계약·원장·설치 별칭 유지 | D-699 관측 원장의 설치 회귀까지 확인하고, 읽기 전용 기록 창을 검증한다. |
| 작업 규칙 추출 | 실제 Fleet 규칙 결과의 동일 사건 기준 | 규칙만 적용한 기준을 생산한다. 정상·지원 불가·관측 부족을 구분하고 가짜 모델 호출·판정을 만들지 않는다. |
| 중앙 판단·결과 연결 | Qwen 기본 판단, 불일치·응답 문제의 OpenCode GLM 검토 | 같은 사건·근거·프로파일·예산을 결속하고 승인된 행동의 현재 상태 확인까지 연결한다. 정상은 호출·명령 없이 종결한다. |
| 알림·사람 인수 | 최종 미해결 outbox·전송·claim 근거 | Discord 담당 세션과 연결하고 Slack·Telegram도 동일 계약을 쓴다. 전송 수용·팀 확인·최종 인수를 각각 검증한다. |
| 독립 평가 | 고정 cohort·원장 소비자, 팀 검수 정답 | 규칙/Qwen/조건부 검토를 같은 평가 자료로 비교한다. 확률 JSON은 독립 보정 전에는 자동 처리 확신의 증거가 아니다. |
| 제한 모델 토론·개선 | 공통 역할 프로파일로 Jev·Laya 등 교체 | 횟수·시간·비용·도구 한도 내 검토 후 실패 자료를 검수한다. 분리된 평가와 회귀 통과 뒤 고정 revision으로 승격·복귀한다. |

첫 현장 수용은 Pinky 차선 정지·재관측 사례에서 관측→판정→제한 처리→물리 결과 확인→피드백을 추적하고, 정상 미개입과 최종 미해결 인수를 함께 입증해야 한다. 수용 세트의 관측 부족 처리 오류·위험 누락·다른 사건 조치·정상 불필요 명령은 0건이어야 한다. 나머지 정확도·보정·지연·비용 한계는 팀의 정답 검수 후 확정한다. 모델 합의나 높은 자체 확률만으로 수용하지 않는다. 관측 누락 때문에 0건을 주장할 수 없으면 HOLD다. 전체 목표 완료에는 위 7단계의 운영 연결·범용 domain 계약·교체 가능한 역할 프로파일·독립 평가·제한 토론과 개선 승격·복귀의 실제 검증도 필요하다. 첫 사례나 source 회귀 통과만으로 목표를 완료하지 않는다.

최신 D-699 source checkpoint는 commit `0bedd7809c719edb9bdf2e78759bf529b1257e08`로 로컬 main에 착지했다. 관측 원장 실제 `fleet.observe` 분리·기존 identity aliases·capture metadata·기존 curation exporter의 읽기 전용 window와 단독 JSON CLI를 연결했다. API v1.217과 동료 Cam·Discord·프로필 계약을 함께 보존했다. 적격 AI PC 9GB의 관련 17개 파일 원격 시험 318 passed, terminal exit 0, known-failures NEW 0과 lint를 확인했다. 이전 넓은 통합의 6,337 passed/295 skipped와 API 버전 동기화 실패 8건은 별도 RED 증거이며 수정본 전체 CI 통과로 바꾸지 않는다.

고정 로그는 `X:/DevTemp/projects/rosy-platform/2026-10-12--033443--deliberation-local-gateway--fc42b3/logs/observation-land-0bedd7809c/run-1.txt`, SHA256 `32d5747a5b201315adec93a665de5ad2e27b5790dbb0109f5e1ae8fbfeca7e9d`다. wheel→별도 target 설치→`python -I -S` import·identity·SQLite capture가 최종 회귀에 포함된다. sdist·실제 모델 품질·서비스 배포·현장 수용·push는 미확인이다. 다음은 실제 규칙 기준 생산과 사건 원장 연결이며, 정상 명령·모델 호출·재발은 별도 완전한 기록 확보 전 0건으로 주장하지 않는다. 이 목표 전체는 ACTIVE다.

D-698 source checkpoint: 단독 primary worker와 receipt/export /3, 녹화·실패 분석·독립 소비자의 역할 결속은 commit `1b434c6aed7af3888adeab3e61590999efdd87fb`로 로컬 main에 착지했다. 적격 Model PC 9GB의 관련 13개 파일 원격 통합 시험 236개, known-failures 신규 실패 0건과 lint를 통과했다. 독립 검토의 역할 결속 지적을 공통 JSON 계약으로 수정하고 재현 RED와 최종 GREEN을 확인했다. 고정 로그는 `X:/DevTemp/projects/rosy-platform/2026-10-12--033443--deliberation-local-gateway--fc42b3/logs/primary-land-1b434c6aed/run-1.txt`이며 SHA256은 `1fa746fd7f105c3d6471bb1078a77c62466e32ba6e7184f12f88f34bdcc7a352`다.

단독 구성은 실제 한 역할 프로파일과 선언된 budget, primary 시도만 결속한다. 정상 상태는 무호출이며 재평가가 필요하면 미구성 모델을 호출하지 않고 최종 인수한다. 기존 두 역할 /1·/2와 비용·인수 근거를 유지하며 JSON CLI와 기존 호출자까지 연결했다. 규칙 생산, 정상 명령·재발의 완전한 기록 범위, 독립 정답·한계와 승격·복귀는 여전히 미완료다. 실제 Qwen·GLM 호출, 독립 품질, 배포·현장 수용과 push는 이 checkpoint에 포함하지 않는다. 전체 운영 비교와 FIELD는 HOLD다.

이전 source checkpoint: D-696 인수 export와 D-697 독립 원장 소비자는 commit `3a431bbc53`로 로컬 main에 착지했다. 적격 AI PC 9GB의 관련 12개 파일 원격 통합 시험 219개, known-failures 신규 실패 0건과 lint를 통과했다. 인수 근거와 독립 소비자에 대한 독립 검토의 중요 지적은 수정했다. 고정 로그는 `X:/DevTemp/projects/rosy-platform/2026-10-12--033443--deliberation-local-gateway--fc42b3/logs/operational-land-3a431bbc53/run-1.txt`다.

소비자는 실제 paired export의 원장 상태 건수·한계 비용·UNKNOWN 예약 책임과 고정 cohort를 연결한다. 누락·변조·학습/보정/평가 ID와 원본 hash 중복, budget·종결 상태 모순을 거절한다. 기존 export /1과 선택 /2, 직접 producer 객체와 단독 JSON CLI를 유지한다. 단독 CLI는 설치된 contract wheel 없이 source checkout에서도 동작한다. 모든 출력은 HOLD이며 관측 종료를 인과적 성공률로 표시하지 않는다.

아래 3의 근거 생산과 4의 첫 소비자는 구현됐지만 전체 운영 성과 비교는 미완료다. 규칙·Qwen 단독 생산 기준, 독립 정답·수용 한계, 정상 명령과 재발의 완전한 기록 범위, 실제 청구·런타임 수용이 여전히 필요하다. 실제 제공자·독립 품질·운영 활성화·현장 수용과 push는 이 checkpoint에 포함하지 않는다.

| 순서 | 작업 | 완료 증거 |
|---|---|---|
| 1 | 소유자 확인·모델 원장 도구 분리·작업 규칙 추출 | 기존 책임·import·패키지 경계와 원격 회귀 유지 |
| 2 | 중앙 판단·결과 연결 | Fleet/Qwen 불일치·응답 문제에서 제한된 GLM 재평가; 같은 사건·근거·예산 결속 |
| 3 | 알림·최종 사람 인수의 실제 근거 export | D-696 동일 snapshot 검증; queue·전송 수용·claim 구분; Discord 설정은 담당 세션 |
| 4 | 독립 운영 성과 비교 | D-697 규칙/기본 모델/조건부 검토의 같은 cohort 비교; 정상 명령·재발·비용 증거 누락은 HOLD |
| 5 | 제한 모델 토론·개선과 승격·복귀 | 고정 프로파일과 보정 기준, 독립 회귀·운영 readback·새 사건 활성 revision |

기존 1·2의 source 구현과 비용·실패 분류 연결은 로컬 main에 있으며 실제 제공자·운영 활성화·현장 수용은 완료하지 않았다. 3의 인수 근거 생산부터 이어서 구현한다. GLM은 기본 Qwen 호출 도구가 아니라 조건부 재평가 경로다. Jev·Laya 등은 동일 역할 계약의 프로파일로 교체하며 Fleet에 모델별 판단 분기를 추가하지 않는다. 독립 운영 평가의 책임·자료 생산·누락 기준은 [D-697](../adr/D-697-independent-operational-comparison.md)로 고정한다. 아래 과거 checkpoint는 당시 증거이며 최신 상태와 구분한다.

| 요구 | 책임과 완료 증거 |
|---|---|
| 판단·현장 연결·설치 분리 | 모듈 import 경계·소유자·원격 회귀 |
| 정상 상황 미개입 | 정상 입력에서 모델/명령 0회, 미개입 종결 원장 |
| 정지·문·암 등 범용 사건 | domain별 승인 schema·근거·성공 확인 계약 |
| Fleet·Qwen 불일치 GLM 검토 | 동일 사건 바인딩과 제한된 호출 원장 |
| 확률 JSON과 모델 자동 처리 | schema conformance + 독립 calibration + 기존 admission |
| Jev·Laya 등 모델 교체 | 역할 프로파일 교체 시험; 실행 중 사건 revision 고정 |
| 사람 최종 검토와 팀 알림 | 예산 소진/지원 불가/결과 불명 인수; 전송과 인수 readback |
| 자체 개선 | 실패 원인→검수→분리된 학습/평가→회귀 비교→승격/롤백 |
| 실제 성공과 증거 구분 | 소스/원격/호스트/제공자/독립 품질/배포/현장 개별 receipt |

## Phase 0: 현재 요구와 책임 고정

Record: D-679, D-681와 이 계획. 기존 `docs/plans/2026-10-11-fleet-deliberation-loop.md`, 책임 분리 계획 및 Model PC 평가 계약을 함께 읽는다. 실제 소스·서비스·운영 프로파일 소유자를 확인한다. Discord 설정은 담당 세션에 남긴다.

## Phase 1: 동일 사건의 조건부 판정

Execute: `2026-10-12-conditional-fleet-qwen-glm-review.md` Task 1.

- `operations/decision/src/rosy/decision/deliberation/`: 기본 의견·Fleet 불일치·검증된 prior·조건부 재평가.
- `operations/fleet/fleet/server/incident_deliberation.py`: scoped Fleet 기준과 현재 값 확인.
- `operations/fleet/fleet/server/deliberation_journal.py`: 정책/사건/예산 재사용 금지.

먼저 RED → 최소 구현 → 커밋 HEAD 원격 GREEN → known_failures 비교 → 독립 검토 → 승인된 로컬 착지. 현재 Assessment에 처리 방향이 없으면 값을 추정하지 않는다. 비교 기준 생산은 실제 Fleet 규칙 결과의 의미를 검토한 뒤 연결한다.

## Phase 2: 실제 제공자 한 번과 교체 경계

Execute: 같은 계획 Task 2–3. 고정 GLM 요청·전용 계정·secret 비노출·namespace·시간/출력/호출 한도를 확인한다. Qwen은 직접 기본 추론으로 유지한다. Jev/Laya는 공통 제공자 계약으로 역할별 프로파일을 정의한다. 정확한 설치 모델·지원 입력·비용·격리·schema가 없는 프로파일은 미수용 상태로 둔다. 모델 종류별로 Fleet 코드에 분기하지 않는다.

## Phase 3: 확률 판정 JSON과 독립 보정

Extend: 기존 `operations/decision/src/rosy/decision/model_tool_contract.py`, `model_tool_catalog.py`, `deliberation/` 경계를 읽고 D-681 판정 계약의 별도 버전을 추가한다. 기존 D-640 parser는 유지한다. probability sum/NaN/중복/다른 사건/없는 evidence/없는 calibration/초과 출력 RED 시험을 먼저 작성한다.

Evaluation: `tools/decision_replay.py`, 기존 `operations/fleet/test/test_deliberation_replay.py`와 Model PC 독립 평가 경로를 재사용한다. 모델 revision·문제 유형별 실측 선택 정확도·보정 오차·확률 구간별 신뢰도를 계산한다. 팀은 정답과 평가 한계를 최종 검수한다. 0.95/0.20 초기 기준을 실측 확인 없이 자동 처리 승인으로 기록하지 않는다.

## Phase 4: 모델 주도 처리·결과 확인

Read/extend: 기존 Fleet model-feedback dispatcher, Mission journal 및 `operations/fleet/fleet/stuck/pipeline.py`의 admission 경계. allowlisted 관측·처리 단계를 모델이 선택하고 매 단계의 현재 사건·안전·예산을 다시 확인한다. CORE 명령 경로를 새로 만들지 않는다. 실제 처리 후 현재 상태 readback과 성공 근거로 종결한다. 결과 불명·재시작·다른 사건·사람 점유에서 재발행을 거부하는 시험을 넣는다.

## Phase 5: 사람 최종 인수와 팀 전달

기존 outbox·사건 원장을 재사용한다. 단순 낮은 확률을 즉시 사람에게 넘기지 않고 허용된 근거 수집/다른 모델 검토를 먼저 수행한다. 최종 예산 소진·지원 불가·결과 불명에 사건 요약·판정 차이·시도·현재 위험·필요 검토를 전달한다. Discord 세션과 상태/중복 키/인수 계약을 맞추고 Slack·Telegram 어댑터에도 같은 계약을 적용한다. 외부 실제 발송은 사용자가 지정한 경로와 설정에서만 수행한다.

## Phase 6: 실패 피드백과 제한된 개선

Reuse: `learning/curation/perception/incident_feedback.py`, 기존 독립 replay 및 registry promotion 경계. 실패 원인을 판정/관측/지도/설치/장치로 분리하고 팀 검수 결과를 기록한다. 개선 후보를 과거 문제와 새 문제에 비교해 위험·정상 개입·종결·지연·비용 회귀를 검사한다. 승격은 고정 프로파일 revision으로 수행하고 진행 중 사건과 원래 원장/예산은 유지한다.

## 실행 상태 (2026-10-12)

Phase 0·1의 ADR·조건부 검토 source는 로컬 main에 착지했다. Phase 2의 GLM 영속 1회 표식과 Phase 3의 v2 프로파일·판정·공통 CLI 요청·독립 보정은 `daccbd38be`로 로컬 main에 착지했다. 보정은 모델 프로파일 전체 SHA-256에 고정하며 모델·역할·어댑터·한도 변경 시 다시 수용해야 한다. 원격 component 증거와 미확인 범위는 `../validation/deliberation-host-admission-2026-10-12/versioned-judgment.md`에 둔다.

실제 GLM 첫 호출은 관리자 설치 명령을 준비했으며 실행 receipt를 아직 확인하지 못했다. Phase 4~6의 운영 루프·최종 인수·개선 승격과 현장 수용은 완료하지 않았다.

Phase 4의 선택적 읽기 전용 worker와 Phase 5의 최종 실패 outbox 연결은 작업 브랜치 `c41fbba181`에서 관련 9개 파일 원격 시험 151개와 신규 실패 0건을 확인했다. 이어 실제 원장 구현을 `automation/ledger`로 분리하고 기존 import 경로·클래스 identity를 유지했다. 실제 wheel/sdist 설치·책임 크기·기존 resolver loop를 포함한 15개 파일 원격 시험 375개, known-failures 신규 실패 0건, lint를 통과하여 `819a6e3140`으로 로컬 main에 착지했다. 호출·관측·비용 한도와 사건/정책 고정, 취소·재시작·사람 점유·다른 사건·새 관측 검사를 포함한다. 실제 서비스 factory와 수용 프로파일 연결, 실제 Fleet 규칙의 동등한 비교 기준 생산, 물리 처리 admission과 현장 종결 증거는 아직 없다. worker 기본값은 비활성이다. 다음 연결 순서는 [실제 런타임 수용 계획](2026-10-12-incident-runtime-admission.md)에 기록했다.

Phase 6의 단일 사건 읽기 전용 export와 기존 녹화 feedback 연결은 `9078a72586`으로 로컬 main에 착지했다. 관련 6개 파일 원격 시험 185개와 known-failure 비교에서 신규 실패 0건을 확인했다. 현재 모델 자료는 `UNREVIEWED`이며 팀의 정답·현장 수용·훈련 데이터로 자동 승격하지 않는다. 판정 JSON의 확률과 원래 입력을 비용 기록과 함께 고정하는 작업, 독립 후보 비교, 승격·복귀는 후속 작업이다.

후속 브랜치 `e0666b3e3f`에서 검증된 원래 입력·판정·전체 프로파일을 원장의 실제 시도 비용과 연결하고 export 재검증을 추가했다. OpenCode GLM v2 요청·prior·응답을 공통 판정 계약에 연결하며 기존 v1 설치 경로를 유지했다. 실제 설치 패키지·모듈 책임 경계를 포함한 9개 파일 원격 통합 시험은 적격 Model PC 9GB에서 204 passed, exit 0이다. 실제 런처 비용 receipt·운영 수용 연결과 provider/독립 품질/배포/현장 증거는 별도로 남아 있다. 이 source 시험은 모델의 정확도나 현장 종결을 증명하지 않는다.

## 완료 기준

D-731 후속 source는 기존 Fleet 단일 제출 소유자에 model/rule claim 소비, ROOT 명시 구성, ACK/UNKNOWN 기록과 worker 결과 확인·최종 인수를 연결한다. 별도 명령 서비스를 만들지 않는다. 정상 미개입과 CORE 정지 경로를 유지한다. 실제 독립 평가 원본 producer·설치 수용 getter·현재 프로파일 설정과 제한 실제 모델 호출·Pinky 현장 수용·승격/복귀는 별도 미완료다. source provider fixture를 실제 Qwen/GLM 호출이나 현장 정답으로 사용하지 않는다.

2026-10-12 D-730 후속: 운영 수용·폐기 epoch와 단일 사건 rule/model 제출 원장을 기존 Fleet DB에 구현했다. 후보 원장은 `automation/operating`으로 책임을 옮기고 기존 import identity를 보존했다. 원격 SQLite 경합·만료·HOLD·서명 변조·기존 PENDING/UNKNOWN 차단과 실제 HttpRobotClient 최종 guard, source 없는 wheel/sdist import를 검증했다. 이 기록은 메커니즘 source 증거다. 실제 resolver/worker 소비 경로, 독립 평가 원본 producer와 설치 증거 연결은 아직 미완료이며 운영 활성화를 허용하지 않는다. AI PC의 `/opt/rosy-deliberation/review-cfcba82ddf` 설치는 재확인 시 없었고 준비 스크립트만 존재했다. 실제 Qwen/GLM 호출과 현장 결과 확인, 실패 피드백의 독립 평가·승격·복귀 수용까지 전체 목표를 닫지 않는다.

최신 checkpoint: 기존 사건 원장과 resolver loop에 선택적 모델 worker를 구성하는 factory, 최종 검토 outbox 연결, GLM v2 의존성/import closure는 commit `3e2f3b9fda`로 로컬 main에 착지했다. D-685 자율 복구 변경을 함께 보존한 13개 관련 파일 원격 통합 시험은 적격 Model PC 7.3GB에서 288 passed, exit 0, known-failures 신규 실패 0건이며 lint도 통과했다. 로그는 `X:/DevTemp/land/feat-conditional-model-review/run-1-1.txt`다. 기본 비활성·같은 DB·사람 점유 차단·UNKNOWN/재발행 거부 경계를 유지한다. 위의 과거 checkpoint에서 미구현으로 적었던 factory는 이제 source 구현되었으며, 실제 서비스 설정과 수용 프로파일 연결은 여전히 남아 있다.

AI PC의 임시 비특권 환경에서 해시 고정 wheel의 오프라인 설치, pip 의존성 검사, v2 import/codec probe가 exit 0과 `PASS_V2_IMPORT_CODEC_ONLY`로 끝났다. 모델 호출은 0회이며 root 설치·서비스 계정 격리·실제 제공자·과금·독립 품질·현장 수용을 증명하지 않는다. 설치 묶음과 실제 확인 범위는 [import closure 기록](../validation/deliberation-host-admission-2026-10-12/versioned-import-closure.md)에 둔다. 다음 작업은 상세 비용 증거를 공통 사건 원장에 연결하고, 실제 Fleet 비교 기준과 수용된 제공자·보정 프로파일을 구성하는 것이다. Discord 설정은 담당 세션이 유지한다. 목표는 아직 진행 중이며 푸시·운영 활성화는 수행하지 않았다.

2026-10-12 checkpoint: Phase 2·3과 Phase 4의 예산 원장·기존 관측 읽기 포트는 `daccbd38be`로 로컬 main에 착지했다. 원격 24개 관련 파일의 364개 source 시험과 known-failure 비교에서 신규 실패 0건을 확인했다. 판단 계약·provider 연결·독립 평가를 실제 하위패키지로 분리했으며 기존 부모의 크기 기준과 +150 한도를 유지했다. 푸시·배포·실제 GLM·현장 수용은 포함하지 않는다. worker·최종 사람 인수 연결은 별도 작업 중이다. Phase 6의 구체적 실행 순서는 [실패 피드백·개선 계획](2026-10-12-model-improvement-feedback.md)에 기록한다.

각 단계의 소스·원격·호스트·실제 제공자·독립 품질·배포·현장 증거를 구분한다. 모델 간 합의나 JSON 성공만으로 현장 완료를 선언하지 않는다. 관측 부족·위험 누락·다른 사건에 조치·정상 불필요 명령 0건 수용 기준은 유지한다. 모델 교체 시 같은 계약/근거/안전/종결 검증이 그대로 통과해야 한다.
