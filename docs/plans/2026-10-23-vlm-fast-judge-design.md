# VLM 빠른 판단: 전처리 · 닫힌 질문 · 확률 읽기 (모바일 로봇 · 로봇암)

**상태:** 설계 제안(2026-10-23). 코드·모델 설치·AI PC 활성화·사진 보관을 승인하지 않는다. 권한 경계는 [D-516](../adr/D-516-offline-decision-model-replay-boundary.md), 켜는 관문은 [D-610](../adr/D-610-ai-first-problem-resolution.md), 모델 출력 범위는 [D-492](../adr/D-492-d438-vision-tier-local-qwen-ai-pc-gated.md)를 따른다. 로봇암은 [D-794](../adr/D-794-omx-camera-roles-top-fixed-front-wrist.md) 카메라 역할과 rosy-vault V-021 배치 증거 계약을 따른다. 실행 순서는 [실험 계획](2026-10-23-vlm-fast-judge-experiment.md)이다.

## 왜 바꾸는가

지금 [`Vlm.judge`](../../operations/situation/rosy_situation/incidents/vision.py)는 Qwen3-VL-8B에 사진마다 설명을 생성시키고(최대 96토큰 × 사진 수), 다시 판단·이유·평가를 JSON으로 생성시킨다. 모델 PC에서 사진 한 장에 1.5–3 s다(D-492). 필요한 답은 `WAIT`·`RESUME` 같은 닫힌 단어 하나인데 글을 생성하느라 느리다.

JEV·SemIf(구 OpenJev)는 글을 생성하지 않고 선택지 토큰의 확률을 한 번의 forward에서 읽는다. 같은 방식을 이미지 입력 모델에 쓴다.

## 구조

```text
케이스(천장 crop + 전면 1장 + 상황)
  → 1. 전처리(규칙, 모델 없음)   ── 실패 → unknown, analyzer 제안 유지
  → 2. 닫힌 질문 확률(모델)       ── 사진 prefix 1회 + 질문 suffix N개
  → 3. 결정 표(규칙)              ── 기준 미달 → unknown, analyzer 제안 유지
  → Fleet 사실 / 그림자 기록 (CORE 권한 변화 없음)
```

모델은 **보이는 사실**만 답하고 행동은 규칙 표가 고른다. D-492 rev 2의 "정체 사실" 방향과 D-516의 "AI PC는 사실, Fleet이 결정"에 맞는다.

## 1. 전처리

| 단계 | 규칙 | 실패 시 |
| --- | --- | --- |
| 신선도 | 천장 ≤ 2 s, 전면 ≤ 3 s(D-610). 두 장 모두 있음. 천장 대상 로봇 식별됨 | 모델 호출 안 함 |
| 화질 | 흐림(라플라시안 분산), 노출 히스토그램, 전흑·전백. 알려진 카메라 이상(감마·짧은 노출·스트림 시작 오프셋)을 여기서 거른다 | 해당 사진 질문은 `unclear` |
| 영역 | 천장: 로봇 둘레 crop(현행). 전면: 바닥·차로 영역 crop | — |
| 크기 | 사진 종류별 고정 해상도, 모델 패치(Qwen 28 px)의 배수. 실험으로 정한다 | — |
| 오버레이 | 모델에는 원본만. 인식 결과(주행 가능 영역·목표선)는 사실 카드의 숫자로 | — |
| 사실 카드 | analyzer가 이미 계산한 값만 약 200토큰: 문제 종류, 막힌 시간, 최근 시도와 결과, 경로 의도 유효 여부, 센서 나이. 12 KB JSON을 넣지 않는다 | — |

현행 프롬프트의 경고문(오버레이·나이·보정 해석) 대부분은 전처리가 대신하므로 빠진다.

## 2. 닫힌 질문

사진 종류마다 질문 묶음을 고정한다. 답은 선택지 토큰 확률로만 받는다. 사진과 공통 지시는 한 번만 계산하고(prefix/KV 캐시) 질문만 바꿔 붙인다.

| 사진 | 질문 id | 선택지 |
| --- | --- | --- |
| 전면 | `front.lane_obstruction` | yes / no / unclear |
| 전면 | `front.thing` | wall / object / robot / person / none |
| 전면 | `front.lane_tape` | both / left / right / none |
| 전면 | `front.shape` | bend / blocked / straight / unclear |
| 천장 | `top.robot_adjacent` | yes / no / unclear |
| 천장 | `top.ahead_space` | free / occupied / unclear |

- 확률은 표시된 선택지에 조건부일 뿐 보정된 신뢰도가 아니다. 질문마다 사람 정답으로 temperature를 맞추고 기준값을 정한다.
- 장면이 바뀌면(맵·조명·횡단보도) [D-162](../adr/D-162-scene-context-profiles.md) 장면 프로파일로 질문 묶음과 기준값을 고른다. 몇 개의 예시를 지시문에 넣는 방식(few-shot)은 토큰이 늘어 쓰지 않는다. 정답이 쌓이면 LoRA로 학습한다.
- 질문 추가·변경은 질문 id와 선택지를 버전으로 고정한다(현행 `PROMPT_ID`와 같은 역할).

## 3. 결정 표

질문 사실 + 사실 카드 → 문제 종류별 허용 단어(현행 `WORDS`). 예:

| 조건 | stuck 결정 |
| --- | --- |
| EMERGENCY 상태 | WAIT |
| `front.thing=person` 또는 `top.robot_adjacent=yes` | WAIT / YIELD |
| `front.shape=bend` 이고 `front.lane_obstruction=no` | RESUME |
| `front.lane_obstruction=yes` 이고 `front.thing∈{object,wall}` | BACK_AND_RETRY 후보, 최근 시도 실패면 MANUAL |
| 어느 결정 질문이든 기준 미달 | unknown → analyzer 제안 유지 |

표 자체는 실험에서 사람 답과 맞춰 고친다. 위험한 움직이는 답(D-610: 동료·물체 쪽 후진, 사람·물체가 있는 횡단보도 `RESUME`)은 표가 만들 수 없게 한다.

## 로봇암(OMX)

같은 세 단계(전처리 → 닫힌 질문 → 규칙 표)를 쓰되, 판단 지점과 권한이 다르다.

**지금 상태:** 팔에는 이미지 판단이 연결되어 있지 않다. 파지는 그리퍼 위치·전류로 판정하고(rosy-vault `device_core/verification.py` `grasp()`), 배치는 외부 관측기 자리만 있다(같은 파일 `placement()`, `PlacementEvidence`, V-021). D-782 사전 점검기는 관절 상태만 보고 이미지를 쓰지 않는다. 정책은 LeRobot ACT이며 성공을 판정하지 않는다(V-018).

**카메라:** `top`은 작업대 위 고정(약 650 mm, 640×480, 보정 미검증), `front`는 실제로 손목 카메라이며 `wrist`로 이름을 바꾸는 중이다(D-794 Proposed).

| 판단 지점 | 사진 | 질문 id | 선택지 |
| --- | --- | --- | --- |
| 집기 전 | top | `top.object_at_pick` | yes / no / unclear |
| 집기 전 | top | `top.place_slot_free` | yes / no / unclear |
| 파지 확인(VERIFY_HOLD) | wrist | `wrist.object_in_gripper` | yes / no / unclear |
| 놓은 뒤(VERIFY_RELEASE) | top | `top.object_at_target` | yes / no / unclear |
| 놓은 뒤 | top | `top.object_pose` | upright / fallen / unclear |
| 놓은 뒤 | wrist | `wrist.gripper_empty` | yes / no / unclear |

**권한 규칙:**

- 사진만으로 파지·배치 성공을 만들지 않는다. 성공은 센서 판정(그리퍼 위치·전류, 릴리스 상태)과 이미지 사실이 **둘 다** 기준을 넘을 때만이다. 이미지 사실이 `no`이거나 기준 미달이면 성공 증거를 내지 않는다(`PlacementEvidence` 없음 → 기존대로 HOLD). 이미지는 성공을 막을 수는 있어도 혼자 열 수는 없다.
- 결과는 vault의 `PlacementEvidence`(success·reason·captured_at·source) 관측기로 들어간다. 관측기 구현은 rosy-vault가 소유하며 V-021 계약을 바꾸지 않는다.
- 집기 전 질문은 정책을 시작하지 않을 이유(대상 없음, 놓을 자리 점유)만 낸다. 시작 허가가 아니다.
- top 카메라 보정이 미검증이므로 픽셀에서 거리·자세를 추정하지 않는다. 슬롯 영역은 설정된 고정 ROI로 자르고 사실 카드에 `calibration=unverified`를 적는다.
- 자동 재시도는 만들지 않는다. 실패는 지금처럼 HOLD이고 `/recover`는 사람이 한다.

**판정에서 가장 중요한 오류:** 실패를 성공이라고 하는 경우(거짓 성공)다. 모바일 로봇의 「위험한 움직이는 답」과 같은 무게로 0건을 기준으로 둔다.

## 데이터

- 로봇암: `learning/curation/omx/native_review.py`의 사람 `outcome`(success·failure·unknown)과 `native_segments.py`의 구간별 결과·개입 기록이 있는 실물 녹화를 쓴다. 질문별 사실 정답은 따로 단다. 시뮬레이션 정답(`sim_object_truth.py`)은 하네스 확인용이고, 정확도 근거로 쓰지 않는다. 2026-10-23 확인: top·wrist 두 장과 사람 `outcome`이 함께 있는 실물 녹화는 시험 PC 세 대에 없다(아래 실험 계획 「데이터 확인」).
- 모바일 첫 실험: D-610 재생 세트(D-607 막힘 39건, 9dfk·8kcn 횡단보도 주행, 2026-10-09–10 현장 기록). 사람 정답은 결정 하나가 아니라 **질문별 사실**로 단다.
- 39건은 방향 확인용이다. 질문별 보정과 승격 증거로는 부족하다.
- 현장 사진은 지금 보관하지 않는다(D-610: AI PC는 sha256만, Fleet은 메모리만). 정답셋을 늘리려면 사례 사진을 모델 PC로 보내 보관하는 경로가 필요하고, 이는 별도 ADR과 사용자 결정이다.
- 평가는 묶음별로 낸다: 사진 종류, 맵, 조명, bend↔blocked, 벽 테이프↔바닥 테이프.

## 실행기

| 후보 | 이미지 + 선택지 확률 | prefix 캐시 | 메모 |
| --- | --- | --- | --- |
| transformers 직접 | 됨 | 직접 KV 재사용 | 실험용. 방식 검증에 쓴다 |
| vLLM | 됨 | 됨 | 저장소에 아직 없음. AI PC 도입은 별도 결정 |
| Ollama 0.35.1(현행) | 됨(2026-10-23 확인, `logprobs`·`top_logprobs`) | Ollama 자체 | 질문 4개 p50 0.18 s, 설명 호출 1회 1.7 s([벤치](../validation/vlm-question-bench-2026-10-23/result.md)). 운영 1순위 |

모델은 먼저 현행 Qwen3-VL-8B로 고정해 방식만 비교하고, 그다음 Qwen3.5-4B·9B(기본 모델에 이미지 내장)를 같은 하네스로 비교한다. JEV-27B-VL은 GPU 메모리가 맞을 때만 기준선으로 본다. Kev는 텍스트 전용이라 이 작업에서 제외한다.

## 열린 결정

1. 사례 사진 보관 경로(ADR, 사용자).
2. AI PC 실행기: Ollama 확률 읽기로 지연 목표를 만족하므로 vLLM은 정확도 비교에서 Ollama 양자화가 문제로 드러날 때만 다시 본다.
3. 질문별 기준값과 지연 목표(실험 결과로 제안).
4. 로봇암 배치 관측기를 rosy-vault에 언제 구현할지(V-021 범위 안, 실물 수용 별도).

## 질문 설계 규칙 (2026-10-23 벤치에서)

- 서로 반대인 질문 쌍(예: `wrist.object_in_gripper`·`wrist.gripper_empty`)을 함께 묻고, 둘 다 같은 쪽이면 모순으로 보고 기권한다. 노란 손가락 패드를 물체로 본 오답이 이 검사로 걸렸다.
- 한 선택지로 쏠리는 질문(`front.thing` → `wall`)은 문구·선택지를 고친 뒤에 정답을 단다.
- 천장 질문은 대상 로봇 crop을 받은 뒤 설계의 로봇 단위 질문으로 쓴다. 장면 단위 질문은 해상도에 따라 답이 뒤집혔다.
