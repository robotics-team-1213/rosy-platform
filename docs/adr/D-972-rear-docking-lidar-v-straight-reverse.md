## D-972 후진 도킹의 위치 근거는 LiDAR V 표지이고, 레일 안에서는 조향하지 않는다

**Status:** Proposed (2026-11-03, 사용자 지시로 구현; 독립 리뷰·`Safety-Review:`(D-430 §5)·Gazebo·실물 수용 전. 기본은 꺼져 있다)

잇는 결정:

- [D-950](D-950-docking-direction-rear-entry.md): 도킹 진입 방향은 후면이다. Decision 3이 위치 근거를 후속으로 남겼다 — 이 ADR이 그 후속이다.
- [D-200](D-200-docking-owns-the-docking-mode.md): 도킹은 DOCKING 모드와 전용 슬롯을 쥔다. 바꾸지 않는다.
- [D-350](D-350-dock-hardware-phase-tiers.md) Phase 1: 도크 계측 없는 전압 1소스 충전 판정. D-27 억제 입력이 아니다.
- 설계 근거(Git 밖 조사 자료): `Rosy/docs/research/pinky-usb-dock-guide-2026-11-01/README.md` 「벽 마찰 · 롤러 · LiDAR 표지(2026-11-03)」, `dock_sim.py`.

### Context

- 걷어낸 충전소(기둥 75.8 · 옆벽 28 · 레일 15 mm)는 RPLidar C1 스캔면(125 mm)보다 낮아 로봇이 충전소를 볼 수 없었다. 후진이라 앞 카메라는 반대쪽을 본다. D-950 후보 중 「도크 DB 자세로 오도메트리 후진」은 회전 3°가 25 cm에서 1.3 cm라 단독 근거로 약하다(D-941).
- 연구 시뮬레이션(`dock_sim.py`, 두 바퀴 준정적 모델, 벽 쿨롱 마찰 근사)에서, 바퀴 옆면은 축 바로 옆(앞뒤 약 9 · 옆 55 mm)에서 레일에 닿아 마찰 μ > 0.16이면 스스로 잠긴다(μ 0.3에서 47개 출발 중 3개). 바퀴 레일을 롤러로 바꾸면 곧게 후진 44 ~ 45/47이지만, 레일 안에서 조향하면(LiDAR 추종) 벽과 다퉈 12 ~ 27/47로 떨어진다.

### Decision

1. **위치 근거는 충전소 뒤 LiDAR V 표지다.** 기둥 뒤 바닥판에 스캔면을 가로지르는 V자 날개 둘(높이 140, 로봇 쪽으로 열림)을 세우고, CORE가 이미 받는 스캔 표본(`core.bridge.observation`)에서, 도킹이 도크를 찾고 맞추는 동안(ACQUIRING · ALIGNING)만 `core_features.docking.lidar_v`가 V를 찾아 `dock_feed`에 `dock/observation` 모양(source `LIDAR_V`, tag_id null)으로 멈춤면 가운데와 안쪽 축을 넣는다. control 패키지(크기 래칫 15555)와 `ros_bridge.py`(870)는 늘리지 않는다. 모양이 다르면(날개 하나·평평한 벽·다른 각도·뒤에서 본 V) 보이지 않음으로 낸다.
2. **정렬은 레일 입구 밖에서만 한다.** 기종 `approach: "rear"`(검출기 `lidar_v`)는 Nav2로 스테이징 자리에 뒤를 도크 쪽으로 두고 선다. V가 보이면 후진하며 축 쪽으로 조향해, 멈춤면에서 `rail_entry_m`(기본 0.45 m)에 닿을 때 횡 ±10 mm · 각 ±2° 안이어야 레일에 들어간다. 아니면 재시도다.
3. **레일 안에서는 각속도 0으로 곧게 후진한다(`REVERSING`, 25 mm/s).** 관측도 조향도 하지 않는다. 진행이 0.5 s 동안 2 mm 미만이면 멈춤면 접촉으로 보고 멈춘다.
4. **충전 판정은 전압 1소스다(D-350 Phase 1).** 멈춘 뒤 0.6 s에 기준 전압을 잡고, 10 s 동안 떨어지지 않으면서 기준보다 0.02 V 오르면 DOCKED. 멈춘 직후 부하가 빠져 오르는 전압을 충전으로 읽지 않기 위해서다. D-27 억제에는 쓰지 않는다.
5. **실패는 레일 밖으로 곧게 전진(0.55 m)한 뒤 스테이징부터 다시, `max_retries`(3) 뒤 DOCK_FAILED.** 언도킹도 후진형은 앞으로 떠난다.
6. **기본은 꺼져 있다.** `docking.supported: false`와 기존 기종의 동작은 그대로다. 도크 DB에 rear 기종을 등록하고 능력을 켠 로봇만 이 경로를 쓴다.

### Consequences

- 바뀐 코드: `docking/rear_phases.py`(새, 단계와 그 상태), `manager.py`(진입점만 — 크기 래칫 771 유지), `database.py`(`approach="rear"`, `rail_entry_m`, 정렬 허용치), `model.py`(`REVERSING`, 이득·속도), `feed.py`(출처별 최신 관측), `detector.py`(`lidar_v` 선택), `docking/lidar_v.py`(새, V 검출), `core/bridge/observation.py`(`rear_dock_scan`).
- 남는 것: 독립 리뷰와 `Safety-Review:`(D-430 §5, 도킹 조향 경로), D-950 Decision 4(후진 장애물 정지·면제 — REVERSING은 레일 안 25 mm/s · 접촉 정지뿐이다), D-397 안전 봉투, 실물 수용(C1에서 V 점 수·잡음, 바퀴 전류 신호, 팩 전압 상승 폭 0.02 V, 레일 롤러 마찰).
- 바퀴 전류나 USB 전원(VBUS) 신호가 생기면 접촉·충전 판정에 더한다. 지금은 오도메트리 진행과 팩 전압뿐이다.
