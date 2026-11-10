# D-922 Pinky 캐릭터 표현 구현 검증

- 검증 소스: commit `939c3f5892` (the pre-port branch tip, before D-949 and the module split; the port onto current main re-ran the focused face, gateway, services and architecture suites).
- 결정: [D-922](../../adr/D-922-pinky-calm-curious-character-expression.md), [설계](../../plans/2026-10-30-pinky-character-expression-design.md).
- 범위: CORE의 검증된 감지 입력 → 표현 정책 → 기존 표정 서비스·로컬 LCD hand-over·후면 LED. 호스트 시험 결과이며 DEVICE/FIELD 수용은 아니다.
- 원격 시험 PC: model PC와 AI PC. 노트북에서 pytest를 실행하지 않았다.

## 구현 결과

사람 방향의 짧은 눈인사, 다중 대상 선택과 무리 fallback, 새 물체의 관심 반응, 실제 도착 전이에 대한 만족, 안전한 일반 대기 300초 후 졸린 휴식을 구현했다. 표정과 후면 LED는 같은 의도를 사용한다. 수평 시선은 ±6px, 전환은 0.4초이며 기존 8종 표정과 자산 생성기를 재사용한다.

감지 신선도·모델 세대·중복과 seq 손실·모드 전환·필수 카드에 따라 반응을 취소한다. 선택적 표현은 독립적으로 0.3초 만료하고 중립 얼굴은 기존 1초 발행 주기를 유지한다. 기존 안전·정보·전력 카드와 경보 LED의 꺼진 구간도 표현보다 우선한다. 주행·팔 명령 writer와 전력 정책은 바꾸지 않았다.

기본 detector는 `track_id`를 보내지 않으므로 현재 기본 입력은 무리 방향 인사를 사용한다. 개별 인사와 재인사는 ID를 제공하는 계약 입력에서 지원한다. 실제 장치의 사람별 추적을 수용한 것으로 해석하지 않는다.

## 실행 증거

| 범위 | 소스 | 통과 | 건너뜀 | 최종 NEW |
|---|---|---:|---:|---:|
| 표정 정책·bridge·native 집중 시험 | `3d550f49ce` | 536 | 1 | 0 |
| 구조·소유권·harness·native·정책 보완 | `2417f262d6` | 373 | 1 | 0 |
| 공식 FULL 27개 호출 | `939c3f5892` | 38,255 | 2,804 | 0 |
| 깨끗한 main의 G1 타이밍 모듈 비교 | `73a04687655a` | 12 | 0 | 0 |

FULL runner exit는 0이다. `full_invocations` 27개를 원격 CLI가 소비하는 배열로 그대로 전달했다. 합계는 중복 범위를 포함한 호출별 실행 합계이며 고유 시험 개수가 아니다. 모니터링 브라우저 전용 묶음 등 opt-in 시험의 skip을 브라우저 수용으로 세지 않는다. 각 보고서의 요약·SHA-256·NEW/known/flaky 분류는 [보고서 manifest](reports.json)에 둔다. 원본 로그 묶음 이름은 외부 보존 위치의 `pinky-complete-full/run-1.txt`부터 `run-27.txt`까지다.

FULL 최초 실행에서는 아래 기등록 quarantine 시험 2건이 실패했다. 공식 runner가 같은 `939c3f5892`의 두 ID를 단독으로 한 번 재실행했고, 2 passed·exit 0을 확인했다. 최종 분류는 NEW 0, known 0, flaky 2다. 처음 실패한 사실과 재실행 결과를 원본 `run-24.txt` 및 별도 `run-24-rerun.txt`에 보존했다. 통과 합계에는 이 두 재실행 통과가 포함된다.

- `test/test_platform_g1_timing.py::test_coordinated_pairs_pass_both_barriers_within_the_proposed_bounds`
- `test/test_platform_g1_timing.py::test_real_uds_round_trip_stays_inside_the_bound`

깨끗한 main 비교는 12 passed이므로 MAIN-RED가 아니다. 이 비교만으로 첫 실패의 원인을 부하로 확정하지 않는다. 기존 quarantine·타이밍 한계·known-failure 목록은 바꾸지 않았다.

앞선 후보의 구조 오류는 크기 기준표 하향, native 표현 시험 분리, 순수 정책 시험의 services 소유 경로 이동으로 수정했다. 실제 bridge와 model-status store 사이의 통합 시험만 소유권 목록에 명시했다. 커밋된 작업 일지는 원문을 보존하고 정정 항목을 덧붙였으며 기존 journal 예외 데이터는 별도 모듈로 분리했다. C6 seam 허용 목록은 확대하지 않았다.

## 검토와 남은 수용

독립 계약 검토에서 지적한 Emotion 문자열 응답, 캐시 표현 만료, 모드 전환 직전 인사 후보, seq 손실 취소를 각각 RED로 재현하고 회귀 시험으로 보완했다. 최종 FULL은 이 보완을 포함한다. 설치된 renderer와 native helper 소스 폐쇄성은 호스트 시험에서 확인했다.

ARM64 실행·실물 LCD 방향 대응·표정 판독·LED 물리 밝기·장치 성능·현장 주행 수용은 수행하지 않았다. main 착지·push·장치 배포·자동 착지 제출도 수행하지 않았다. 소스 렌더 미리보기는 실제 LCD 촬영이 아니다. DEVICE/FIELD gate는 유지한다.

CE: 해당 없음. 구현과 회귀 시험, 기존 [간헐 실패 귀속 교훈](../../solutions/workflow-issues/attribute-intermittent-failure-by-line-then-interleaved-comparison.md) 및 [FULL 실행 범위 교훈](../../solutions/workflow-issues/full-mode-json-does-not-prove-full-matrix-execution-2026-10-29.md)으로 판단을 복원할 수 있다. 새로운 장치·운영 복구 성질을 발견한 작업은 아니다.
