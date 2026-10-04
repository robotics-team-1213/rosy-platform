# 중앙 Fleet 1단계 실행 계획 (설계: `2026-10-04-central-fleet-step1-design.md`)

**Status:** PLAN rev 1 (2026-10-04). D-454 결정 2의 (1)단계.

## 작업

| # | 작업 | 산출 | 시험 |
|---|---|---|---|
| T1 | `CentralRegistry` 읽기 모델 | `operations/fleet/fleet/server/central_registry.py` | 합산(정적+등록+hub)·정렬·state/capabilities 전달·미계산 |
| T2 | 중앙 라우터 + 프로파일 마운트 | `central_registry_routes.py`, `app.py` `--central` 마운트, `cli.py` 플래그 | 목록 200·상세 200·404 UNKNOWN_ROBOT·401·Viewer 허용 |
| T3 | 문서 갱신 | API Ref §10.1 상태 표기(미구현 → 1단계 관측), `deploy/site/README` 중앙 프로파일 한 줄 | 문서 계약 시험 |
| T4 | 저널·착지 | fleet logs.md, docs/logs.md | lint, known_failures 비교 |

- T1–T2가 이번 회차(작은 회차 두 개보다 하나로). T3–T4 같은 커밋.
- 뒤 작업(별도 회차): §10.1 나머지 7경로 — PATCH/DELETE(등록 저장소 확장), pairing-tokens(D-341 연결), pending/approve(D-361 연결), token revoke.

## 완료 정의

- `/api/v1/fleet/robots`·`/{id}`가 시드 앱의 `--central` 프로파일에서 응답한다.
- ROS-SIM/DEVICE/FIELD 승격을 주장하지 않는다(D-454 결정 3).
