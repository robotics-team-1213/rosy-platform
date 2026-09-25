---
module: games
logical_modules: []
owner: GAMES
last_verified: { commit: "411a303", date: 2026-09-18 }
gates:
  SOURCE:
    state: GO
    evidence: "package.xml, 경계 시험, overhead.py만 cv2. 이미지·슬라이스 미포함 (2026-09-18 Windows)"
    cmd: "python -m pytest src/site/games/test/test_games_boundaries.py test/test_rosy_games_surface.py -q"
  LOCAL:
    state: GO
    evidence: "D-112 stair 1 visibility report; D-113 host track closed (2026-09-18 Windows)"
    cmd: "python -m pytest src/site/games/test test/test_rosy_games_surface.py -q"
  ROS-SIM:
    state: N/A
  ARTIFACT:
    state: N/A
  DEVICE:
    state: PARKED
  FIELD:
    state: PARKED
adrs: [D-90, D-94, D-95, D-96, D-97, D-98, D-99, D-100, D-101, D-102, D-103, D-104, D-105, D-106, D-107, D-108, D-109, D-110, D-111, D-112, D-113]
plans:
  - docs/plans/2026-09-17-robot-soccer-game-host-design.md
  - docs/plans/2026-09-18-rosy-games-local-host.md
  - docs/plans/2026-09-18-rosy-games-overhead-plan.md
  - docs/plans/2026-09-18-rosy-games-remaining-adr-plan.md
---
## 지금 상태

- 노트북 게임 호스트 (D-90). CORE 모드 아님. 최종 `cmd_vel` 없음.
- LOCAL 호스트 트랙 닫힘 (D-113). 계단 1 가시성 보고 (D-112). `--stair 1–5` (D-111). linear ≤ 0.10 (D-110).
- DEVICE/FIELD는 실제 천장 웹캠·마커 실측. `ready`와 pytest는 현장 GO가 아니다.

## 다음 gate

1. D-96 계단 1 실측: `--stair 1 --observer overhead --preview`
2. 그 기기 정지·워치독·단일 publisher 뒤 `--stair 2 --drive rosy_01 --observer overhead --preview`
3. `--stair 3` 이격 → `--stair 4` 1v1 → `--stair 5` 킥오프 반복
4. 계단 4 반복 뒤에만 D-97 온보드, D-98 Isaac, D-99 신경망. 0.20은 그 다음 ADR
