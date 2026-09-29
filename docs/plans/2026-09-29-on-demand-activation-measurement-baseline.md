# 온디맨드 활성화(B레인) 후보 — 측정 기준선

**날짜:** 2026-09-29 · **관련:** D-347(C레인 착지), D-185(CPU 예산 순서), D-321(매핑 승인), D-323(Rosy Pilot)
**성격:** 조사·계획. 이 문서는 코드를 바꾸지 않는다. B레인(세션 경계 그래프 기동) 착수 조건인
"실측으로 입증된 낭비"의 현재 상태를 한 장으로 정리하고, 부족한 측정만 남긴다.

## 1. 배경

D-347 토론의 합의: B레인은 **D-185 순서와 같은 관문** — 실측 숫자가 낭비를 입증하는 그래프에만 하나씩.
C레인(단일 생애 어휘 + `activating` 예약)은 착지했다(`baa75363`). 이제 관문 앞의 증거 상태다.

## 2. 하드웨어 상주 세트 인벤토리 (Pinky Pro, native 런타임)

systemd 단위(`deploy/robot/pinky_pro/native/`)와 런치가 정의하는 **부팅 후 상주** 목록:

| 단위 / 진입점 | 실행 내용 | 상주 조건 | 세션 성격 |
|---|---|---|---|
| `rosy-core.service` | CORE 게이트웨이(단일 프로세스, D-1) | 항상 | — (게이트웨이 자체) |
| `rosy-io.service` | `bringup_robot.launch.py` — 모터·LiDAR·ADC·배터리 | `ROSY_RUNTIME_MODE`×`ROSY_IO_DRIVE_ENABLED` 행렬 검사 통과 시 | **후보 아님** — 안전·구동 기본층 |
| `rosy-camera.service` | `control camera_preview.launch.py`(OV5647 캡처+OpenCV) | 항상(`PartOf=rosy-runtime.target`) | **후보 1순위** — 대시보드 프리뷰·비전 증거 요청 시에만 의미 |
| `rosy-navigation.service` | `navigation hardware.launch.py`(Nav2 또는 SLAM 백엔드, D-144) | `ConditionPathExists=/etc/rosy/approvals/{hardware,navigation}.approved` — **부팅 승인제**(D-321) | **후보 2순위** — 이미 조건부 상주다. B레인은 "부팅 승인"을 "세션 승인"으로 미는 것과 같다. 특히 SLAM 백엔드: 매핑 세션에만 필요 |
| `line_follow.launch.py` include | IR/카메라 라인 센싱 | `enable_line_follow` **기본 false**(부팅 인자) | **이미 해결된 사례** — 온디맨드가 아니라 부팅 옵트인으로 처리됨. B레인 설계의 참고 형태 |
| boot-display·login-code·hw-probe·config 등 | 짧은 주기 보조 단위 | 조건부 | 후보 아님(경량) |

io 이미지의 패키지 클로저(`test_io_image_closure`가 고정)에는 omx_adapter·control이 포함되지만 OMX는
ER2 트랙(D-327 어댑터)이 밟는 중 — **후보 3순위, 지금은 건드리지 않는다**.

## 3. 기존 실측 정리 (재측정 금지 — 이미 있는 숫자)

| 출처 | 무엇을 쟀나 | 숫자 |
|---|---|---|
| D-185 본체(x86 rig, 2026-09-23) | control Python 노드 6개의 상주 CPU | 합계 **2.16 코어**(606 s 통과 실행). 웨이크업 90–210/s, 주벙 `/tf`(노드당 ~25/s)·`/clock`(50–110/s). web·goal·wander는 CPU의 68–84%를 콜백 **밖**에서 |
| D-185 격리 실험 | 빈 구독 15개 노드 1개의 비용 | `SingleThreadedExecutor`+`/clock` 300 Hz = **50–58%**; `EventsExecutor` = **15%**; 30 Hz = 18% |
| D-185 R1 | `inflate` numpy 재작성 | 200×200: 48→**6 ms**(Pi 실측 포함) |
| D-185 R8(Pi 5, release 005, 2026-09-24) | **CORE만 구동** 상태의 바탕 부하 | 부하 ~0.3, **한 코어의 ~22%**. `watch`(노드별 CPU)와 R3 EventsExecutor 실기 비교는 **아직** |
| D-185 R8 | 다음 핫스팟 후보 | `match_motion` 73 ms(50 ms 교정 tick 초과) — 회전 stall 원인 경로 |

## 4. 갭 — 온디맨드 판정에 필요하고 없는 측정

1. **카메라 파이프라인의 상주 비용(Pi)**. R8은 CORE만 돈 상태였다 — `rosy-camera`(캡처+OpenCV)가 붙은
   상태의 코어·메모리 측정이 없다. 측정: 입회 하에 `systemctl stop rosy-camera` A/B(`watch` 도구,
   R8과 같은 절차). 낭비 입증 → 세션화(대시보드 프리뷰 요청 = 세션) 파일럿.
2. **SLAM 백엔드 상주 비용 vs 로컬라이즈 백엔드(Pi)**. 매핑 세션(D-321, 승인 뒤에만 시작)이 끝난 뒤에도
   SLAM 그래프가 승인된 이상 상주한다. 백엔드별 부팅 상태 측정이 없다.
3. **R3 EventsExecutor 실기 A/B**. 온디맨드와 독립적이지만 상주 비용의 절반을 차지할 수 있는 항목 —
   D-185 완료 조건에 이미 걸려 있다(노드가 바퀴를 움직일 수 있어 입회 필요).

## 5. 절차 원칙 (D-185 Decision 2 준용)

- **도구**: `deploy/robot/pinky_pro/verify/measure-resident-cpu.sh` — 단위별 CPU를 cgroup/proc 틱으로
  샘플하고 `--ab-unit`(카메라·navigation 만 허용, 측정 뒤 되살림)로 A/B 를 잰다. 안전 경계는
  `test/test_measure_resident_cpu.py`가 고정한다.

- 모든 측정은 **실기 입회**(DEVICE gate). 바퀴가 돌 수 있는 상태의 실험은 사용자가 로봇 옆에 있을 때만.
- A/B는 같은 도구, 교차 반복(R8 방식). 부하·환경은 rig 가드 기준(R4)을 준용해 무효 실행을 센다.
- 낭비 입증 전에 그래프를 내리는 코드 변경은 없다(결함 없는 동적화 금지, D-347 토론 합의).
- 입증된 후보 하나당: 후속 ADR(`activating` 생산자 허용 + 세션 경계 정의) → 파일럿 → D-347 불변식
  (`withheld`==`unavailable`, `activating` 무생산 핀 해제)를 그 ADR에서만 연다.

## 6. 비목표

ROS 그래프 구동·서비스 단위 변경·본 문서의 숫자 외 추정. OMX(ER2 진행 중). CAP-003 게이트·
readiness(D-58)·cmd_vel 단일 발행(D-2/D-38)의 변경.
