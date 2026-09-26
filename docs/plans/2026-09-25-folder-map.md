---
module: docs
---

# 현재 폴더를 읽는 지도

**Status:** 2026-09-25, D-229 이후. 패키지 이름은 바꾸지 않았다. `src/runtime` 은 없다.

실행 기준은 [D-227](../adr/D-227-ownership-names-stay-on-the-current-tree.md), [D-228](../adr/D-228-decision-lives-in-core-features.md), [D-229](../adr/D-229-layer-boundaries-on-the-current-tree.md) 다. 래퍼 루트에 두었던 구조 스냅샷은 이 지도로 대체한다.

## 래퍼와 정본

`Rosy/` 는 git 이 아니다. 정본은 `Rosy OS/` 다. 래퍼에는 `archive/`, `.worktrees/`, 이미지 산출물만 남긴다. 계획 문서는 `Rosy OS/docs/plans/` 다.

## 소스

```text
src/
├── core/          런타임, 판단, 센싱
│   ├── core/                      최종 cmd_vel
│   ├── core_features/
│   │   ├── decision/              동작 id. 속도 없음
│   │   ├── line_follow/           FOLLOW 다음의 속도 식
│   │   ├── command/               명령 선택
│   │   └── safety/                상한과 정지. 판단 제공자 아님
│   └── control/
│       └── sensing/
│           ├── lidar, body, dock  기하. perception 을 import 하지 않음
│           └── perception/        카메라·차선 증거. ROS 없음
├── devices/       버스와 칩
├── products/      omx_adapter. 기본 꺼짐
├── face/          LCD
├── navigation/    Nav2
├── sim/           URDF, Gazebo
└── site/          fleet, games
```

## 그 밖

| 자리 | 두는 것 |
|---|---|
| `deploy/` | 이미지, SD, 제품 유닛, 서명 |
| `tools/` | 개발 PC 절차, 인식 재생 |
| `docs/adr`, `docs/plans` | 결정과 계획 |
| `docs/validation/` | 날짜가 있는 측정 |
| `data/teleop`, `data/drive` | 세션 |
| `private/` | 공개하지 않는 초안. git 밖 |
