## D-228 판단은 `core_features/decision` 이다 — 런타임 개명과 제품 이름 패키지는 만들지 않는다

**Status:** Accepted (2026-09-25). 인식 코드와 `control` 패키지는 옮기지 않는다.
입력은 저장소 밖 `ROSY_Decision_Fabric_AI_Judgment_Architecture_v0.8.md` 다.
잇는 결정:

- D-2, D-38: 최종 `cmd_vel` 은 `core` 다.
- D-168, [D-227](D-227-ownership-names-stay-on-the-current-tree.md): 영역 루트는 지금 일곱 개다. `src/runtime` 을 만들지 않는다.
- D-205, D-209: `control` 분할과 `sensing/perception/` 은 실측 순서 뒤다.
- D-215: 로봇 ack 의 `TIMEOUT` 은 Fleet 기록이다. 이 결정의 `TIMEOUT` 은 판단 상태다.
- `src/AGENTS.md`: `rosy_*`, `pinky_*` 디렉터리 이름을 다시 두지 않는다.

**Context:**

1. **v0.8 이 나눈 세 질문은 이미 자리가 다르다.** 보이는 것은 `control/sensing` 이다. 허용된 선택 중 고르는 것은 공유 라이브러리다. 고른 뒤를 바퀴로 만드는 것은 `core_features/command` 와 `core` 의 최종 속도다. 안전 정지는 그 판단의 제공자가 아니다.
2. **v0.8 의 `src/runtime/rosy_pinky_pro` 는 공유 몸통을 한 제품 이름으로 만든다.** 인식과 주행 실행은 Pinky 와 OMX 가 같이 쓰는 `core` 와 `control` 에 있다. 제품 기록은 D-207 의 매니페스트·천장·URDF 다.
3. **`rosy_decision` 이라는 새 ROS 패키지는 부르는 쪽이 둘이기 전에 열리면 빈 패키지다.** 판단 계약은 `core_features` 가 이미 둔 ROS 없는 라이브러리 계층에 들어간다. 원격 모델과 사이트 워커는 이 폴더가 호출하지 않는다.
4. **기존 차선 if/else 를 이 변경에서 옮기면 D-205 의 순서를 앞당긴다.** 라이브러리는 제품이 넘긴 허용 집합과 규칙 함수만 받는다.

**Decision:**

1. **폴더는 이렇게 읽는다.**

   | v0.8 이름 | 자리 |
   |---|---|
   | Perception | `src/core/control/control/sensing`. `perception/` 은 D-209 의 시점 |
   | Decision | `src/core/core_features/core_features/decision` |
   | Command authority | `core_features/command`, `core` 브리지 |
   | Safety | `core_features/safety`. 판단 제공자가 아니다 |
   | Product execution | `control` 의 실행 모듈과 `navigation`. `rosy_pinky_pro` 가 아니다 |
   | Heavy judge / training | `tools/perception`, `data/teleop/learning`. `src/site/rosy_ai_worker` 가 아니다 |

2. **`src/runtime`, `src/contracts`, `src/site/rosy_ai_worker`, `rosy_pinky_pro`, `rosy_manipulation` 은 만들지 않는다.** D-227 의 영역 금지를 유지한다.
3. **판단 결과는 허용된 동작 id 다.** `selected_action` 은 상태가 `DECIDED` 일 때만 있다. 집합 밖 id 는 `INVALID` 이고, 그 id 를 합법적인 값으로 고쳐 적지 않는다. `ERROR` 와 판단 `TIMEOUT` 은 그 상태로 남고, 폴백은 다른 필드다. 이 라이브러리는 ROS 를 import 하지 않고 `cmd_vel` 을 만들지 않는다. `SAFE_STOP`, `EMERGENCY`, `MANUAL` 은 `motion` 인 선택지를 규칙보다 먼저 뺀다.
4. **지금 차선·도킹·배회 코드는 그 자리에 둔다.** 한 판단 종류를 이 라이브러리로 연결하는 일은 그 종류의 별도 변경이다.

**Consequences:** v0.8 의 최종 런타임 트리는 폴더 이름이 아니다. 다음 패키지 이동이 `src/runtime` 을 만들면 D-227 과 이 결정을 어긴다. 원격 provider 는 이 폴더에 없다.

**Validation:** `python -m pytest src/core/core_features/test/test_decision.py -q`
