# 차선이 사라져도 예상 경로를 다시 내는 방식 — 테슬라 공개 자료와 ROSY

> 조사: 2026-10-10. 일차 자료는 Tesla 특허 공개본, Karpathy의 게시, Ashok Elluswamy의 글, Tesla AI Day 발언 기록이다. 코드 줄 번호는 브랜치 `docs/expected-path-hold`에서 이 보고서 직전의 트리이다. 설계 계획은 [2026-10-10-expected-path-hold.md](2026-10-10-expected-path-hold.md)이다. 이 문서는 그 계획의 근거이고, 구현 지시가 아니다.

## 결론

테슬라가 공개한 동작은 마지막 영상을 얼려 두는 것이 아니다. 카메라 특징을 시간과 이동 거리로 쌓고, 차가 움직인 만큼 그 특징을 맞춘 뒤, 차선 점과 앞으로의 궤적을 다시 예측한다. 페인트가 없는 교차로도 그 예측의 대상이다.

ROSY의 drivable keep은 그렇게 하지 않는다. 길이 1.5초보다 오래되면 조향 오차를 내지 않는다. 1.5초 기억은 회전 래치를 지울 타이머일 뿐, 마지막 목표를 이어서 쫓지 않는다. CORE의 D-476 브리지는 짧은 공백을 오돔으로 잇지만, 직전 추종이 안정적일 때만, 몸 진행 방향으로, 그리고 기본은 꺼진 채다.

[예상 경로 계획](2026-10-10-expected-path-hold.md)이 가져가는 것은 이 재발행이다. 매 프레임 오돔 위의 경로를 다시 내고, 마스크가 비면 이동량만큼 옮겨 가까운 접선으로 조향한다. 먼 끝점은 길이 상한이다. 가져가지 않는 것은 2025년에 Ashok이 밝힌 끝단 신경망, 즉 픽셀에서 조향과 가속을 바로 내는 구조다. 화면의 파란 선이 가속과 정지를 색으로 나눈다는 설명은 이차 자료라 이 결론의 근거로 쓰지 않는다.

## 조사 범위와 자료 등급

질문은 하나다. 차선이나 drivable이 한 프레임 사라질 때, 테슬라는 예상 경로를 계속 계산해 보여 주는가. 그 메커니즘 가운데 ROSY가 이미 가진 것과 계획에서 거절한 것은 무엇인가.

일차 자료는 문서 소유자가 쓴 글과 저장소 소스다. 이차 자료는 그 문서를 풀어 쓴 기사다. 이차 자료의 문장으로 특허 청구항을 대신하지 않았다. 열지 못한 문서는 아래 「확인하지 못한 것」에 둔다.

## 테슬라가 공개한 것

### 시간과 거리로 쌓는 특징 큐

2021년 8월 19일 Tesla AI Day에서 Karpathy는 프레임마다 잊는 문제를 이렇게 말했다. 특징 큐에 카메라 특징과 차의 운동(속도, 가속도)을 넣고, 시간으로도 거리로도 쌓는다. 시간 큐는 약 27 ms마다 넣어, 앞차가 잠시 가려져도 직전 특징으로 검출을 유지한다. 시간만 쓰면 빨간 신호에서 기다리는 동안 예전에 본 차선과 표지를 잊는다. 그래서 일정 거리를 갈 때마다 넣는 공간 큐를 더한다. 이 발언은 AI Day 영상 기록이다. Tesla 백서가 아니다. [영상 기록](https://www.youtube.com/watch?v=FwT4TSRsiVw)

같은 구조가 특허 본문에 있다. Tesla의 차선 연결 네트워크는 멀티카메라 융합 결과를 video queue에 넣고, 시간이 지날 때마다 또는 차가 일정 거리(예: 0.2 m, 1 m, 3 m) 움직일 때마다 갱신한다. 정렬은 예를 들어 20 m 앞선 프레임의 특징을, 지금 위치 기준으로 세로와 가로로 옮겨 맞춘다. 운동 정보로 속도, 가속도, 요 각속도를 든다. 출원 [US 2024/0062556 A1](https://patents.google.com/patent/US20240062556A1/en)은 2026-02-10에 [US 12,548,351 B2](https://patents.google.com/patent/US12548351B2/en)로 등록됐다. 가출원은 2022-08-19, 출원은 2023-08-18이다.

이것이 아닌 것: 마지막 마스크를 픽셀 그대로 유지하는 일. 큐에 남는 것은 융합된 특징이고, 정렬 뒤에 네트워크가 다시 점을 낸다.

### 차선을 점으로 다시 쓰기

2022-03-14 Karpathy는 FSD Beta 10.11 릴리스 노트에서 차선 기하를 dense raster(“bag of points”)에서, transformer로 벡터 공간의 차선을 점마다 예측하고 연결하는 autoregressive decoder로 바꿨다고 적었다. [게시](https://x.com/karpathy/status/1503211737046085634)

특허는 그 디코더가 교차로에서 하는 일을 적는다. 교차로 너머의 어느 차선이 어느 차선으로 이어지는지는 페인트가 끊겨 있어 한 장의 점으로 정하기 어렵다. 네트워크는 언어 모델처럼 한 차선을 잇따른 점으로 서술하고, 합류와 분기를 점의 속성으로 붙인다. 같은 설명은 자차의 미래 위치를 autoregressive하게 추정해 궤적을 만들 수 있다고 적는다. 상한은 시간 단계 또는 추론 횟수다. [US 2024/0062556 A1](https://patents.google.com/patent/US20240062556A1/en)

이것이 아닌 것: 이번 프레임에 흰 선이 보이면 그 선만 따라가고, 안 보이면 경로 발행을 멈추는 일.

### 끝단 신경망은 다른 계약이다

2025-10-24 Ashok Elluswamy는 ICCV 발표의 축약으로, Tesla의 자율주행이 끝단 신경망이라고 썼다. 입력은 여러 카메라의 픽셀, 속도 같은 운동 신호, 음성, 지도와 내비게이션이다. 출력은 차를 움직이는 제어 명령이다. 입력 규모를 보이는 예에서 이력은 30초, 운동은 100 Hz이고, 줄어드는 출력은 다음 조향과 가속도 두 토큰이다. [Tesla's approach to Autonomy](https://x.com/aelluswamy/article/1981644831790379245)

ROSY가 이 계약을 가져가면 차선 오차와 신뢰로 CORE가 속도를 내는 지금 경계가 사라진다. 계획은 이 층을 거절한다.

### 점유 격자

Tesla 공식 채널의 [AI Day 2022](https://www.youtube.com/watch?v=ODSJsviD_SU)는 1:12:11에 “FSD | Occupancy Network” 장을 둔다. 이 조사는 그 장의 대본을 확보하지 못했다. 점유가 빈 공간과 속도를 복셀로 낸다는 식의 설명은 이차 기사에만 있어 메커니즘 근거로 쓰지 않는다.

## 화면의 경로와 차선 페인트

특허가 말하는 미래 궤적과, 운전자 화면에 그려지는 선은 같은 문장으로 확인되지 않는다. 화면 선의 색이 가속과 정지를 나눈다는 설명은 [Not a Tesla App의 시각화 목록](https://www.notateslaapp.com/tesla-reference/636/all-tesla-fsd-visualizations-and-what-they-mean)에 있다. 이차 자료다. 페인트가 없는 길에 가운데 선을 그린다는 주행 영상 해설도 같은 등급이다.

따라서 “보여 준다”는 이 보고서에서 다음만 뜻한다. 예측된 경로가 네트워크 출력으로 다시 계산된다. 그 출력을 로봇 디버그에 실어 사람이 보는 일은 ROSY 계획의 범위이고, 테슬라 화면의 색 규약은 근거가 아니다.

이차 기사가 특허 번호로 적은 US 2026/0170852 A1은 이 조사에서 원문을 열지 못했다. 연 문서는 위 2024년 공개와 2026년 등록본이다. [Not a Tesla App, 2026-06-28](https://www.notateslaapp.com/news/4334/how-teslas-fsd-solves-lane-connectivity-how-fsd-works-part-6)은 그 번호의 안내일 뿐, 청구항의 출처가 아니다.

## ROSY에 이미 있는 것

drivable 길이 없으면 조향이 끊긴다. `keep_step`은 `latest_way(WAY_MAX_AGE_S)`가 비면 `steer.lost`를 부르고 `(None, False)`를 반환한다. `WAY_MAX_AGE_S`는 1.5다. 주석은 그 사이를 테이프 keeper로 조향하지 말라고 한다.

```45:49:middleware/perception/control/sensing/perception/drivable_keep.py
    # No fresh way: hold. The tape keeper on the boundary strips must not steer in between
    # (its corners and one-sided targets fought the way, 8kcn 20261009T234748Z).
    steer.lost(stamp)
    last.update(strategy='none', reason='drivable_way_stale', error=None, confidence=None, target_m=None)
    return None, False
```

`lost`는 `FORGET_S`(1.5 s) 뒤에 래치를 지운다. 그 동안 오차를 내지 않는다 (`learned/drivable_steer.py:82`, `:273-278`). 길이 있을 때의 조향점은 `LOOKAHEAD_M` 0.25 m 근처 행의 중심이다 (`learned/drivable_steer.py:35`, `:100`). 한 점이지, 시작과 끝으로 확정한 구간이 아니다.

CORE는 관측이 `stale_after_s` 0.3초를 넘으면 HOLD하고, `lost_after_s` 3.0초를 넘으면 LOST로 잠근다 (`line_follow/model.py:87-89`, `line_follow/manager.py:613-615`, `:735-740`). 신뢰는 선속도에 곱해진다. `min_confidence` 0.35일 때 배율은 `(confidence - 0.35) / (1 - 0.35)`다 (`line_follow/manager.py:398-405`).

D-384의 `road_state`는 이미 오돔 거리로 COAST·SLOW를 나눈다. 1.08배 이동이 0.10 m 미만이고 2.5초 이하면 COAST, 0.25 m 미만이면 SLOW다 (`road_state.py:53-58`). 이 출력은 명령을 내지 않는다. [D-476](../adr/D-476-lane-loss-expected-road-bridge.md) 결정 6은 브리지가 켜진 동안 이 COAST를 `visible = true`로 CORE에 넣지 않는다. 같은 공백을 두 번 잇지 않기 위해서다.

D-476 브리지의 진입 사유는 `line_not_visible`, `observation_stale`, `no_observation`뿐이다 (`lane_bridge.py:22`). 이동은 명령 적분이 아니라 오돔이고, `bridge_slow_m` 0.25 m 또는 `lost_after_s`에서 0.5초를 뺀 시각에 끝난다 (`model.py:246-248`, `lane_bridge.py:203-211`). 목표까지의 앞 거리는 `bridge_lookahead_m` 0.10 m다. 기본 `bridge_enabled`는 꺼져 있다.

`line/keep_debug`는 관측 전용이다. `lane_debug.py` 첫 문단이 그 그림을 인식이나 동작에 되돌리지 않는다고 적는다 (`lane_debug.py:1-4`). 페이로드는 keeper `last`를 복사한다 (`lane_debug.py:34-44`).

## 계획이 가져가는 것과 거절하는 것

[예상 경로 계획](2026-10-10-expected-path-hold.md)은 위 일차 자료와 지금 코드의 빈칸을 이렇게 자른다.

가져가는 것:

- 매 프레임 경로를 다시 계산해 낸다. 특징을 얼리지 않는다.
- 이번 프레임에 길이 없으면, 직전 가설을 오돔 이동으로 옮겨 다시 낸다. 특허의 frame alignment와 같은 방향이다. 구현은 특징 맵이 아니라 이미 받아들인 직선 구간 하나다.
- 조향은 가까운 접선이다. 먼 점은 0.25 m 길이 상한이다. 0.25 m와 0.10 m, 2.5초는 새 상수가 아니라 `bridge_slow_m`, `bridge_lookahead_m`, `road_state`의 SLOW 상한이다.
- 사람이 보는 선은 이미 있는 `line/keep_debug`에 싣는다. 새 외부 API는 없다.
- 공백의 주인은 그 가설이다. 가설이 신선한 관측을 내는 동안 D-476 브리지는 시작하지 않는다. 결정 6의 이중 연장을 피하기 위해서다. `lane_bridge.py`는 고치지 않는다.

거절하는 것:

- Ashok이 2025년에 적은 끝단 계약. 픽셀·음성·지도에서 조향과 가속을 바로 내는 일.
- 먼 끝점을 pure pursuit 목표로 쓰는 일. 특허의 차선 점은 교차로 연결용이고, ROSY 지면 투영의 먼 점은 오차가 큰 쪽이다.
- 회전, 횡단보도, 선 위 몸, 막힌 앞에서의 연장. 특허도 교차로 연결을 힌트 없는 직진 연장과 같은 문제로 두지 않는다. D-476 결정 2는 힌트 없는 교차로에서 브리지를 하지 않는다.
- 점유 격자, autoregressive 차선 문장, 64회 이상 반복 추론. 후자는 이 조사에서 특허 원문으로 확인하지 못한 이차 기사의 숫자다.

## 확인하지 못한 것

- US 2026/0170852 A1 원문. 이차 기사가 가리키는 번호이고, 이 조사는 2024년 공개본과 등록본 US 12,548,351 B2를 읽었다.
- AI Day 2022 occupancy 장의 발언. 공식 영상의 장 제목만 확인했다.
- 운전자 화면의 경로 색과, 페인트가 없는 도로에 선을 그리는 제품 동작. Tesla 문서가 아니라 이차 해설이다.
- 10.11 릴리스 노트 전문. Karpathy가 인용한 한 항목만 일차로 확인했다. 노트 원본 이미지는 인용된 게시의 바깥에 있다.
- Pinky 주행 녹화에서 이 가설의 공백 길이. 계획의 태스크 5이고, 이 보고서의 측정이 아니다.

## 판단

차선이 사라진 프레임에도 경로를 내는 일은 테슬라 공개 구조와 맞다. 그 구조의 핵심은 이동에 맞춰 기억을 옮긴 뒤 경로를 다시 계산하는 것이고, 마지막 그림의 유지나 픽셀에서 조향을 바로 내는 일이 아니다. ROSY는 오돔으로 잇는 거리 사다리와 디버그 토픽을 이미 가지고, drivable keep은 길이 비는 순간 오차를 끊는다. 계획의 가설은 그 빈칸만 메운다. 상한은 이미 있는 0.10 m, 0.25 m, 2.5초를 넘지 않는다.
