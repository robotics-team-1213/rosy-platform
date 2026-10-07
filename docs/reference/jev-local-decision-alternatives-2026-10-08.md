# ROSY AI PC의 Jev 대체 의사결정 모델 조사

**조사일:** 2026-10-08
**범위:** TypeSafe AI의 Jev(`typesafe.ai`)와 ROSY의 로컬 판단·비전·로봇 행동 후보. 조사와 구조 제안에 AI PC의 오프라인 Laya 연결 시험을 덧붙였다. 운전 승인이나 현장 수용은 아니다.

## 결론

ROSY에서 Jev를 **한 모델로 통째로 대체할 이유는 아직 없다.** 현재 가장 작은 실험은 기존 Fleet 규칙과 CORE 재검사를 기준선으로 유지하면서, 이미 시험한 로컬 `qwen3-vl:8b-instruct`가 **장애물의 정체 사실**만 추출하게 하고, 그 사실이 실제 답을 바꿀 만한 막힘에서만 작은 로컬 typed decision 모델을 그림자로 평가하는 것이다. AI PC의 첫 비교 대상은 **Laya 다국어 322M**, 영어 코드화 상태라면 **Laya typed-decisions 421M**과 **Kev 0.8B**다. Jev와 가장 비슷한 멀티모달 공개 가중치 후보는 **Cloudflare Clef-Flash**지만 9B BF16 가중치만 대략 18GB이므로 16GB VRAM의 AI PC에 원본 그대로 상주할 수 없다. 이들 모델을 도입하기 전에도 규칙과 기존 VLM만으로 필요한 답이 나오는지 먼저 측정해야 한다. [Clef-Flash 모델 카드](https://huggingface.co/Cloudflare/clef-flash), [Laya 모델 카드](https://huggingface.co/convaiinnovations/laya), [Kev 모델 카드](https://huggingface.co/jaredpalmer/kev-0.8b), [D-492](../adr/D-492-d438-vision-tier-local-qwen-ai-pc-gated.md), [D-503](../adr/D-503-autonomy-chain-facts-and-exception-queue.md).

## 1. Jev가 실제로 하는 일

TypeSafe의 Jev 1.13은 호스팅된 **텍스트/JSON 입력 → Choice·Score·Noul 및 확률** 모델이다. 영상·음성·이미지를 직접 받지 않고, 로컬 가중치 배포나 고객 데이터 미세조정도 공식 모델 목록에 없다. 버전 고정 ID는 `jev-1.13.0`; 움직이는 alias의 답이 달라질 수 있으므로 비교 실험에는 고정 ID가 맞다. 공식 가격·속도 수치는 공급자 발표값이며 우리 망과 작업의 지연 증거가 아니다. [TypeSafe 모델 문서](https://docs.typesafe.ai/models), [공식 소개](https://typesafe.ai/blog/introducing-system-one-models-and-jev).

Jev의 장점은 선택지를 미리 정하고 확률을 받아 소프트웨어가 분기하기 쉽다는 점이다. **선택지가 유효하다는 것과 답이 맞는 것은 별개다.** 제조사도 수 계산, 시간 비교, 무관한 긴 상태, 적대적 내용, 선택지 순서 편향을 한계로 적는다. 따라서 거리·시간·권한·충돌 여유는 코드/CORE가 계산하고, 모델의 `confidence`를 물리 안전 허가로 쓰지 않는다. [Jev 1.13 한계](https://docs.typesafe.ai/model-jaggedness/jev-1.13), [신뢰도 설명](https://docs.typesafe.ai/confidence).

`jev.ai` 검색에는 TypeSafe 공식 문서가 아닌 제3자 설명·재판매 사이트도 다수 나온다. 이 보고서의 Jev 근거는 `typesafe.ai`와 `docs.typesafe.ai`로 한정했다.

## 2. ROSY의 현재 자리와 장비

| 항목 | 저장소에서 확인한 상태 | 조사에 주는 의미 |
| --- | --- | --- |
| Fleet 막힘 판단 | [D-438](../adr/D-438-fleet-stuck-resolver-rules-model-human.md)의 규칙→비전→사람 구조. 구현 메모상 규칙·사람만 있고 비전 2단계는 없다. | 새 모델이 즉시 운전 답을 내는 단계가 아니다. |
| 비전 입력 | [D-492](../adr/D-492-d438-vision-tier-local-qwen-ai-pc-gated.md)는 LiDAR가 확인한 막힘에 한해 `wall/object/robot/person/unknown` 사실을 요구한다. 사람 정답이 없는 47장 실험은 정확도 수용 증거가 아니다. | 사진 한 장에 Jev를 직접 적용할 수 없다. 현행 Qwen3-VL의 사실 추출부터 V0/V1 검증한다. |
| 권한 | [D-503](../adr/D-503-autonomy-chain-facts-and-exception-queue.md)은 모델→출처·나이 있는 사실, 규칙→답, CORE→최종 재검사, Fleet→예외 큐를 제안한다. [D-392](../adr/D-392-provider-neutral-model-tool-contract.md)는 모델의 직접 주행·정지/해제·장치 구동을 금한다. | 모델 후보는 제어자가 아닌 입력 또는 제안자다. D-503은 Proposed이며 구현·운전 승인으로 읽지 않는다. |
| AI PC / 모델 PC | [D-492](../adr/D-492-d438-vision-tier-local-qwen-ai-pc-gated.md)의 **모델 PC**에는 Ollama `qwen3-vl:8b-instruct` 시험 기록이 있다. **AI PC**는 별도 공유 GPU 노트북이며 RTX 5080 Laptop **16GB VRAM**, RAM **15GB**다. [D-434](../adr/D-434-model-pc-and-site-pc-roles.md)는 모델 PC를 학습·평가에 둔다. | 정확도는 모델 PC에서 오프라인 평가할 수 있다. 실시간 상주·p95 지연·동시 작업 간섭은 AI PC 소유자 동의 후 AI PC에서 따로 측정한다. |
| 다른 숙고형 판단 | [D-331](../adr/D-331-gemini-er2-proposal-adapter.md)과 [D-392](../adr/D-392-provider-neutral-model-tool-contract.md)는 Gemini Robotics ER 2를 Mission/Task **후보**로 다룬다. `POLICY_DISPATCH_ENABLED=False`는 현재 소스의 기본값이다. | 작업 계획과 막힘 정체는 서로 다른 평가 세트가 필요하다. |

## 3. 후보 비교

| 후보 | 입력 → 출력 / 운영 형태 | ROSY 적합성 | 현 단계 판단 |
| --- | --- | --- | --- |
| 기존 규칙 + 로컬 Qwen3-VL 8B | LiDAR·로봇 상태는 규칙, 프레임은 VLM이 정체 사실로 변환. [D-492](../adr/D-492-d438-vision-tier-local-qwen-ai-pc-gated.md), [Qwen3-VL 공식 모델 카드](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct) | 이미 로컬 시험 경로가 있고 D-492가 V0 사람 라벨 50장, V1 그림자 30건 등을 정의한다. 영상의 정체 결과는 로봇 답 자체가 아니다. | **1순위 기준선.** 먼저 유효한 문제 비율과 병목을 잰다. |
| Laya 다국어 322M / typed-decisions 421M | 텍스트 상태 → bounded typed decision, Apache-2.0 공개 가중치. [다국어 모델](https://huggingface.co/convaiinnovations/laya-multilingual), [typed 모델](https://huggingface.co/convaiinnovations/laya-typed-decisions) | 경량 실행은 가능성이 높다. 기본 영어 모델은 제작자의 한국어 intent 시험에서 0.103 정확도로 무작위 0.050에 가까웠다. 다국어 체크포인트도 제작자 카드상 **출시 확률 미보정**, typed-decision zero-shot이 다수 클래스 기준보다 낮다. ROSY 정확도는 없다. | **실행·정확도 탐색 후보**일 뿐이다. 한국어는 다국어, 영어로 정규화한 상태는 typed 모델을 별도로 평가한다. [제작자 실험과 한계](https://huggingface.co/convaiinnovations/laya-multilingual) |
| Kev 0.8B | 텍스트/JSON → Jev 호환 Choice·Score·Noul, Apache-2.0 공개 가중치, 4GB GPU급. [모델 카드](https://huggingface.co/jaredpalmer/kev-0.8b) | AI PC 자원은 가볍지만 영어 전용이고 제작자도 도메인 밖 정확도가 4B보다 크게 낮다고 밝힌다. | **같은 그림자 세트의 비교군.** 기본 권고 모델로 확정하지 않는다. |
| Kev 4B | Jev 호환 typed decision, Apache-2.0 공개 가중치. [모델 카드](https://huggingface.co/jaredpalmer/kev-4b) | 제작자 측정 상주 GPU 메모리 14.3GB. AI PC 16GB에서 단독 실행도 여유가 작고 기존 Qwen3-VL과 동시 상주는 어렵다. 영어 중심. | 소형 후보가 정확도 부족일 때, AI PC GPU 단독 예약 후 비교. |
| 고정 라벨 소형 분류기 | ROSY가 기록한 상태·사람 정답 → 해당 현장 라벨의 분류/확률 보정. [scikit-learn 확률 보정](https://scikit-learn.org/stable/modules/calibration.html) | 라벨이 쌓이면 현장 분포에 맞출 수 있다. 처음부터 열린 자연어 판단 범위를 일반화하지는 못한다. | Jev형 모델과 함께 평가할 **저비용 기준선**. 충분한 독립 라벨이 생겼을 때만 학습한다. |
| Cloudflare Clef-Flash 9B | 텍스트·JSON·이미지·비디오 + Jev형 질문 → 선택지별 확률; Apache-2.0 공개 가중치. `systemone` 헬퍼가 Jev 요청/응답 형식을 받는다. [모델 카드](https://huggingface.co/Cloudflare/clef-flash) | 비전 사실과 typed decision을 한 모델로 시험할 수 있다. 공식 실행 예시는 H200에서만 검증됐다. BF16 9B의 가중치 용량만 약 18GB라 AI PC 16GB 단일 GPU 상주 불가가 합리적 추론이다. 양자화가 joint head 경로까지 보존하는지는 확인되지 않았다. | **연구 후보.** 외부 GPU/메모리 증설 또는 검증된 양자화가 있으면 시험. |
| Cloudflare Clef 27B | Clef-Flash와 같은 typed multimodal 계열, Apache-2.0. [모델 카드](https://huggingface.co/Cloudflare/clef) | BF16 27B 가중치만 약 54GB로 AI PC 범위를 훨씬 넘는다. | 현재 장비에서는 제외. |
| Jev API | 텍스트/JSON → Choice·Score·Noul, 호스팅. [공식 문서](https://docs.typesafe.ai/models) | 비교 기준으로는 유용하나 영상 전처리와 외부 상태 전송·네트워크 의존성이 남는다. | 데이터 전송 승인 범위에서만 오프라인 기준 비교. |
| Gemini Robotics ER 2 | 멀티모달 공간 이해와 작업 오케스트레이션 → 작업/도구 **제안**. [공식 안내](https://ai.google.dev/gemini-api/docs/robotics-overview), [모델 카드](https://deepmind.google/models/model-cards/gemini-robotics-er-2/) | 저장소에 이미 제안 어댑터가 있다. Jev식 빠른 로컬 폐쇄형 선택지 판단의 대체재는 아니다. | Mission/Task 별도 트랙. |
| NVIDIA Cosmos-Reason2 2B | 물리 장면 추론 VLM. [공식 설명](https://docs.nvidia.com/cosmos/latest/reason2/index.html) | 제조사 최소 GPU 메모리가 **24GB**라 현 AI PC 16GB에서 공식 지원 구성이 아니다. [요구 사양](https://docs.nvidia.com/cosmos/latest/prerequisites.html) | 장비 변경 전에는 제외. |
| SmolVLA·OpenVLA·π0 계열 | 카메라·상태·지시 → 관절/엔드이펙터 **행동**. [SmolVLA](https://huggingface.co/docs/lerobot/smolvla), [OpenVLA](https://github.com/openvla/openvla), [openpi](https://github.com/Physical-Intelligence/openpi) | 조작 정책 학습과 장치 action 공간이 필요하다. Pinky 막힘 판단이나 Fleet typed choice 대용이 아니다. | OMX 조작 Skill 연구로 분리. |

**직접 영상→짧은 답을 원한다면** [Qwen3-VL 2B](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct)·[4B](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct) 또는 [Qwen3.5 4B](https://huggingface.co/Qwen/Qwen3.5-4B)도 비교할 수 있다. 이들은 생성형 VLM이라 제약된 JSON/choice 형식은 만들 수 있어도 Jev처럼 보정된 선택지별 확률을 자동으로 얻는다는 뜻은 아니다. D-492의 기존 8B보다 실제로 빠르고 정확한지는 동일 카메라/라벨 세트에서 측정해야 한다. [vLLM 구조화 출력](https://docs.vllm.ai/en/stable/features/structured_outputs/).

**추가 후보의 위치:** [Verdict](https://github.com/Manavarya09/verdict)는 소량 라벨 적응·기권을 내세우는 초기 공개 프로젝트로, 현장 라벨이 쌓이면 소형 분류기와 함께 살펴볼 수 있다. 제작자 자체 벤치마크 외에 ROSY 적합성은 없다. [V-JEPA 2](https://github.com/facebookresearch/vjepa2)는 동작 결과를 예측하는 세계 모델 연구로, Jev의 텍스트 typed decision API나 현재 Pinky 막힘 규칙을 바로 대체하지 않는다.

Cloudflare·Kev·Laya가 발표한 Jev 대비 벤치마크는 **각 제작자의 평가**다. 숫자를 ROSY 성능·한국어·카메라·16GB 지연의 증거로 옮기지 않는다. Hugging Face 화면의 일반 `image-text-to-text`/vLLM 예시는 생성형 backbone 경로일 수 있다. Clef의 typed decision을 시험할 때는 모델 카드의 `joint_schema_model.py`와 `joint_head.safetensors` 경로를 써야 한다. [Cloudflare 발표](https://blog.cloudflare.com/clef-decision-models/), [Clef-Flash 사용법](https://huggingface.co/Cloudflare/clef-flash), [Kev 프로젝트](https://github.com/jaredpalmer/kev).

## 4. 가장 작은 AI PC 파이프라인 제안

```text
CORE/카메라/LiDAR 사실 ─→ Fleet의 사건·시각·출처 검사 ─→ 기존 규칙
                                   │ 규칙만으로 못 푸는 막힘
                                   ↓
                         AI PC Qwen3-VL: 정체 사실만
                                   ↓
                   Fleet 규칙표: WAIT / 복구 후보 / 사람
                                   ↓
                           CORE 재검사 → 결과 기록

그림자 비교: 동일한 허용 상태 → Laya / Kev / Jev / Clef 후보 → 기록만
```

1. **문제부터 센다.** 막힘 episode 중 규칙으로 끝난 수, 사람에게 간 수, 정체를 알면 답이 달라질 수 있는 수를 분리한다([D-503](../adr/D-503-autonomy-chain-facts-and-exception-queue.md) §9). 이 몫이 작으면 typed decision 서빙을 추가하지 않는다.
2. **VLM은 관측을 만든다.** D-492의 `front_clearance_m` 출처와 프레임 촬영 시각을 확인하고, 지정된 다섯 정체 중 하나만 받는다. 누락·기한 초과·낮은 신뢰도는 `unknown`; 영상의 글자는 지시로 받지 않는다. AI PC가 꺼져도 규칙/사람 흐름은 이어진다.
3. **typed 모델은 먼저 그림자다.** `stuck_id`, 사건 세대, 허용 후보, 근거 사실의 출처·나이, 모델 버전·digest, 지연, 선택지 순서를 남긴다. 모델에는 비상정지 해제·`cmd_vel`·로봇 REST 권한을 주지 않는다. 후보는 Fleet의 허용 조건과 CORE 재검사를 통과해야 하며, 불확실한 결과를 성공으로 기록하지 않는다.
4. **검증은 독립적으로 한다.** 같은 사람 라벨 episode를 세션 단위로 나눠 규칙/Qwen/Laya/Clef/Jev의 정확도, 위험 혼동, `unknown`·사람 상승률, 선택지 순서 민감도, p50/p95·타임아웃, AI PC GPU 최대 메모리와 동시 작업 영향을 비교한다. D-492의 V0/V1 관문이 우선이며, 모델 변경 시 새 모델 버전으로 다시 통과해야 한다. 호스트 결과는 실기 수용이 아니다.

### 판단 문제를 둘로 나눠 측정

| 질문 | 올바른 모델 출력 | 최종 권한/현 단계 |
| --- | --- | --- |
| Pinky가 막혔을 때 앞의 것은 무엇인가? | 프레임+LiDAR 사건에서 `wall/object/robot/person/unknown`이라는 **관측 사실**. | D-492 V0/V1을 거친 뒤 Fleet 규칙이 답을 고르고 CORE가 재검사한다. |
| 여러 로봇/OMX 작업의 다음 단계는 무엇인가? | 상태·capability·목표에 대한 **Mission/Task 또는 재계획 후보**. | [D-427](../adr/D-427-platform-three-parts-middleware-operations-learning.md)의 `operations/decision` 자리와 [D-392](../adr/D-392-provider-neutral-model-tool-contract.md)의 Fleet 허용 목록을 쓴다. 현재 자동 정책 배차는 꺼져 있다. 사람 정답·실행 결과와 별도로 비교한다. |

`FOLLOW/SLOW/RECOVER/STOP` 같은 낱말만 모델이 반환하게 하면 실제 CORE 모드·허용 행동·정지 거리와의 관계가 빠진다. [2026-09-25 Decision Fabric 초안](../plans/2026-09-25-decision-fabric-input-v0.8.md)의 선택지 예시는 실행 API 계약이 아니다. 비교용 출력에도 `ABSTAIN/사람`을 두고, 실행 가능한 선택지는 해당 사건의 기존 계약에서만 가져온다.

## 5. 지금 결정할 것과 보류할 것

**권고:** D-492의 로컬 Qwen3-VL 정체 V0 데이터를 먼저 만들고, 그 데이터의 `규칙만으로 모호한 상태`로 Laya 다국어·typed-decisions와 Kev 0.8B를 **동일한 그림자 세트**에서 비교한다. 이 단계에서 어느 후보도 운전 답을 내지 않는다. 어느 후보도 사람 검토를 실질적으로 줄이면서 위험 혼동·지연·확률 보정 기준을 통과하지 못하면 추가 서빙 없이 규칙+VLM+사람으로 끝낸다. Kev 4B는 정확도가 더 필요하고 GPU를 단독 예약할 수 있을 때, Clef-Flash는 AI PC 메모리/런타임 대안을 실측할 수 있을 때 시험한다. Jev는 공식 API에 접근할 수 있더라도 로컬 운전 경로가 아니라 외부 기준선으로만 둔다. [D-492](../adr/D-492-d438-vision-tier-local-qwen-ai-pc-gated.md), [D-503](../adr/D-503-autonomy-chain-facts-and-exception-queue.md).

**미확인:** AI PC GPU 상주 예약/소유자 동의, Laya·Kev의 실제 한국어·로봇 막힘 정확도와 확률 보정, Clef-Flash의 16GB VRAM 양자화와 joint-head 호환, AI PC 동시 Qwen 상주 지연, 사람 라벨 정답 세트, 현장 실기 결과. AI PC에서 Laya의 CPU 연결 시험만 했으며 정확도·실시간 적합성은 확인하지 않았다.

## 6. 모델 교체를 위한 최소 구조

**호스트를 먼저 구분한다.** 모델 PC(D-434)는 재생·정답 평가·학습에 쓰고, AI PC(D-492)는 소유자 동의와 지연 관문을 통과한 **사이트 로컬 추론 후보**다. Laya·Kev는 크기상 모델 PC에서 오프라인 시험할 만하지만, 이 사실만으로 AI PC에서 Qwen3-VL과 동시 상주하거나 운전에 충분하다고 결론 낼 수 없다. Kev 4B는 제작자 측정 상주량만 14.3GB다. [Kev 4B 모델 카드](https://huggingface.co/jaredpalmer/kev-4b), [D-492](../adr/D-492-d438-vision-tier-local-qwen-ai-pc-gated.md).

**교체 경계는 모델 제품명이 아니라 판단 작업이다.**

| 작업 계약 | 입력 → 출력 | 교체 시 고정할 것 |
| --- | --- | --- |
| 막힘 정체 관측 | LiDAR가 연 막힘 사건 + 시각이 맞는 프레임 → `wall/object/robot/person/unknown` 사실 | D-492의 값·출처·나이·시간 초과 처리. Qwen 외 VLM은 이 계약을 맞추고 V0/V1을 다시 통과한다. |
| 숙고형 후보 판단 | Fleet이 만든 제한된 상태 + 사건의 허용 후보 → 후보·분포 또는 기권 | D-427/D-429의 `operations/decision` 소유권과 Fleet admission. Jev/Laya/Kev는 이 자리의 어댑터 후보일 뿐이다. |

따라서 초기 구현에는 **모델별 거대한 공통 런타임이 필요 없다.** 현행 Fleet 판단기 옆의 작은 호출 어댑터가 선택된 모델의 응답을 위 작업 계약으로 정규화하면 된다. 모델 프로파일에는 최소한 `task`, `provider`, 고정 모델 revision/digest, 프롬프트 또는 질문 세트 버전, timeout, 평가 세트 hash와 승인 단계를 묶는다. 설치별 endpoint·비밀은 기존 비공개 설정에 둔다. 전환은 **새 모델을 같은 기록에 그림자로 돌림 → 독립 정답과 지연 비교 → 해당 작업의 승인 프로파일 변경 → 이전 프로파일로 되돌릴 수 있게 보존** 순서다. 모델만 바꾸어도 분포·신뢰도·지연이 달라지므로 threshold를 복사하지 않고 다시 보정한다. 모델 출력이 없거나 늦으면 기존 규칙/사람 경로로 간다. [D-492](../adr/D-492-d438-vision-tier-local-qwen-ai-pc-gated.md), [D-427](../adr/D-427-platform-three-parts-middleware-operations-learning.md), [D-429](../adr/D-429-five-concerns-control-port-and-site-devices.md), [Jev 모델 버전 문서](https://docs.typesafe.ai/models).

현재 소스에는 Fleet의 규칙·사람 막힘 판단기와 ER 2 제안 어댑터가 있지만, `operations/decision`·`integrations/models` 목표 경로는 아직 실제 디렉터리가 아니다. 위 표는 구현된 교체 기능이 아니라 **다음 구현의 경계 제안**이다. 첫 실험은 공급자 서버·공개 REST 경로를 새로 만들지 않고 오프라인 재생 호출로 충분하다.

## 7. AI PC 오프라인 시험 준비와 실행 경계

사용자는 이번 시험 호스트를 **AI PC**로 골랐다. [D-516](../adr/D-516-offline-decision-model-replay-boundary.md)의 첫 실행은 로봇·Fleet과 분리된 `tools/decision_replay.py`다. 한 행의 예시는 아래와 같다. `expected`는 모델 답을 복사하지 않고 검토자가 사건 기록에서 붙인다. 이 예시는 도구 형식 확인용이며 정확도 세트가 아니다.

```json
{"id":"example-1","state":{"cause":"obstacle_ahead","front_clearance_m":0.24,"thing":"person","thing_source":"reviewed_frame"},"instructions":"Given these facts, choose one advisory candidate. Never issue a robot command.","criteria":{"WAIT":"A person or robot is in the way","ESCALATE":"Facts are missing or ambiguous"},"expected":"WAIT"}
```

Laya와 Kev의 공식 서버가 같은 `POST /v1/systemone`을 받으므로 서버만 바꾸고 **같은 JSONL**을 재생한다. 서버는 AI PC의 loopback에만 묶는다. Laya는 `LAYA_HOST=127.0.0.1 LAYA_DEVICE=cuda LAYA_MODELS=multilingual laya-serve`, Kev는 별도 환경에서 공식 `kev.serve`의 loopback 바인딩을 쓴다. 실행 예시는 `python tools/decision_replay.py <평가.jsonl> --endpoint http://127.0.0.1:8000/v1/systemone --model multilingual`이며 Kev를 띄운 뒤에는 포트와 `--model kev-latest`만 바꾼다. 설치 명령·정확한 서버 버전은 실행 때 고정하고 기록한다. [Laya 서버](https://github.com/NandhaKishorM/laya#self-hosting-http-server-jev-compatible), [Kev API](https://github.com/jaredpalmer/kev#api).

2026-10-08에 `ai` 계정으로 AI PC SSH 접속을 확인했다. 첫 실패는 별칭 없이 주소만 입력해 이 Windows PC의 사용자명 `livs`로 접속한 탓이었다. 로컬 SSH 별칭과 비공개 호스트 목록에 올바른 계정을 기록했다. 접속 당시 별도 SAM worker가 GPU 메모리 약 2.1 GiB를 사용 중이어서 이번 Laya 시험은 **CPU만** 사용했다. GPU 점유는 시험 전후 같았고, 시험 서버는 종료했다.

### AI PC 첫 Laya 실측: 연결 시험, 정확도 평가 아님

| 항목 | 확인값 |
| --- | --- |
| 실행 | AI PC의 격리된 `~/rosy-decision-eval/.venv`, Laya 0.4.0, PyTorch 2.14.1+cpu, `LAYA_MODELS=multilingual`, loopback `127.0.0.1:8766` |
| 체크포인트 | `convaiinnovations/laya` bundle revision `7b928d828b7b0e022f929d9bd2e44165aa270148`, 다국어 모델 선택 |
| 재생 | `tools/decision_replay.py`로 만든 인위적 2건. `person`→`WAIT` 기대에 모델 `ESCALATE`, `unknown`→`ESCALATE` 기대에 모델 `ESCALATE`. 1/2 일치, 기권·호출 오류 0 |
| 호출 지연 | 첫 건 160.5 ms, 다음 건 94.8 ms, 두 건의 p95 160.5 ms. CPU·짧은 합성 입력의 수치이며 운영 지연 증거가 아님 |
| 기록 | 입력 SHA-256 `c67ebce24dd11280d3ad3ee07d6d5c38c3d37c31ec721201aeaa98ebb415994e`, 결과 SHA-256 `7c150d05874d50e44eceaa7efeebe99e93e6384f58479ca89d25caaa21153423`; 원본은 `X:\DevTemp\rosy-decision-replay-20261008\`과 AI PC의 시험 폴더에 보관 |

예시 `thing_source` 문자열은 형식 시험을 위해 만든 것이며 실제 검수된 영상 사실이 아니다. 이 두 건으로 정확도, 확률 보정, 정체 위험 혼동률을 추정하지 않는다. Kev는 아직 설치·실행하지 않았다. 다음 비교는 독립적으로 사람이 라벨링한 막힘 사건 세트를 마련한 뒤 같은 입력으로 실행한다. VLM은 [D-492](../adr/D-492-d438-vision-tier-local-qwen-ai-pc-gated.md)의 별도 정체 V0 세트로 시험한다.

## 8. 확정한 호스트와 판단 권한

2026-10-08 사용자 결정으로 [D-516](../adr/D-516-offline-decision-model-replay-boundary.md)을 Accepted로 올렸다. **모델 PC**는 학습·평가·승격 증거와 고정 `ModelProfile` 후보를 만들고, **AI PC**는 승인된 버전의 추론만 한다. **관제 PC의 Fleet**은 AI PC가 돌려준 사실·후보를 검증해 규칙·admission·사람 확인을 적용하고, **로봇 CORE**가 실행 전 다시 확인한다. AI PC가 모델을 실행한다고 해서 Fleet의 판단 권한이 AI PC로 옮겨가지는 않는다. D-434의 기존 모델 PC·관제 PC 역할과 D-492의 막힘 VLM V0/V1 관문은 유지된다. 프로파일의 정확한 전송·인증·활성화 schema는 별도 구현 계약으로 남긴다.
