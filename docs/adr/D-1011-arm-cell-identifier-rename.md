## D-1011 팔 셀 식별자를 CELL-A/cell-a에서 ARM-CELL/arm-cell로 바꾼다 — 입력은 구 id를 별칭으로 받고, 원장은 감사와 함께 한 번 재작성한다

**Status:** Accepted (2026-11-10, 사용자 결정: "rename the OMX arm cell identifier from CELL-A / cell-a to arm-cell … Nothing may break during the switch"). 코드·시험·호스트 스크립트까지, 실제 호스트 전환·현장 수용은 별도다.

잇는 결정: [D-960](D-960-control-unit-per-arm-set-under-integrated-r.md)(암 세트마다 셀 관제) · [D-974](D-974-control-vocabulary-layers.md)(단위·호스트 어휘) · [D-893](D-893-control-unit-host-placement.md)(단위와 호스트 분리)

### Context

- 셀 관제 단위 id `CELL-A`는 임시 이름이 컸다. 호스트 PC는 이미 `rosy-arm-cell`로 이름 붙었고, 단위 id·Compose project·설정 디렉터리·볼륨·peer 이름에 구 이름이 남아 있다.
- 단위 id는 코드에 하드코드되지 않고 `control-unit.yaml`(private)의 `unit_id`·`manifest`·`peers`로 온다. 그래서 전환은 (1) 코드가 구 id 입력을 계속 받아들이게 하고 (2) 원장(DB) 행을 안전히 옮기는 일이다.
- 기존 운영 문서는 "DB를 새 unit ID에 재사용하지 않는다"고 했다(관제 단위 배포 문서). 개명마다 원장을 버리면 진행 중 이력·감사를 잃는다.

### Decision

1. **새 id.** 관제 단위 id는 `ARM-CELL`(단위 id는 대문자 관례, D-974). 호스트 런타임 이름(Compose project, `/etc/rosy/arm-cell`, 볼륨 `arm-cell_arm_cell_data`)은 소문자 `arm-cell`. **peer 이름 `peer-cell-a`와 R의 송신 token 파일 `r-to-cell-a.token`은 이 결정에서 바꾸지 않는다**(나중 단계): R의 peer DNS alias가 compose 서비스 이름에 걸려 있어 단위 id·프로젝트 개명과 같은 창구에서 함께 바꾸면 전환 중 단절된다. 팔 각각의 workcell id(`arm_a` 등)와 `omx_cell_a`류 시험 값은 팔 단위 이름이라 그대로다.
2. **입력 별칭.** `UNIT_IDENTIFIER_ALIASES = {"CELL-A": "ARM-CELL"}` 한 곳에 두고, 입력이 도착하는 모든 경로에서 정규화한다: `ControlUnitTopology.unit()`(모든 범위 해석), peers 설정 key(`peers.CELL-A`), 수신 service principal(`control-unit:CELL-A` — 관제의 첫 인사이자 매 요청의 신원), 정지 ingress의 `target_unit`·`expected_controls` key, `/units/{unit_id}` 조회. 출력·저장은 항상 새 id다. 별칭과 새 key를 동시에 정의하는 peers 설정은 거절을 유지한다.
3. **config_revision은 느슨하게 하지 않는다.** 구 revision을 가진 위임·정지 요청은 기존처럼 거절한다. 양쪽 설정(`unit_id`·manifest·peers·users)은 같은 보수 창구에 갱신한다.
4. **원장 마이그레이션.** `ControlUnitStore`가 identity 충돌 검사 전에 멱등 마이그레이션을 돌린다. unit-id 열은 정확값만 재작성하고, `*_json` 문서는 **정확히 일치하는 값만**(부분문자열 아님) 바꾼다. `fleet_control_unit_identifier_events`에 감사 행(`from_id`·`to_id`·시각)을 남긴다. 재적용은 아무것도 쓰지 않는다. "DB를 재사용하지 않는다"는 일반 규칙에 이 개명만 이 회로로 허용한다(배포 문서 갱신).
5. **호스트 전환은 dry-run 스크립트로.** `tools/ops/rename_arm_cell_runtime.sh`가 팔 세션 lock(`flock -n`, 없으면 거부)·작업 lock·motor-health 상태(`rosy.motor-health.v1`, 두 팔 모두 안전 상태)를 확인한 뒤, **스택을 먼저 끄고**(볼륨 속 sqlite/WAL 정합) 백업 → 볼륨 복사·모든 파일 sha256 대조 → `/etc/rosy/cell-a`를 `/etc/rosy/arm-cell`로 이동하고 compose 키·경로를 재작성(구 경로는 symlink) → Compose project 재기동 → fleet 컨테이너의 새 볼륨 mount 확인·건강 확인(healthcheck 없는 컨테이너는 건강 아님)을 `--apply`일 때만 수행한다. 실패 시 구 스택 `cell-a`를 자동으로 되살린다.

### Consequences

- 전환 창구에 구 설정을 가진 이웃이 남아 있어도 정지·위임 경로가 단절되지 않는다. R의 읽기 요약(overview)은 R 설정 갱신 전까지 자식을 STALE로 표시할 수 있다(표시만 영향).
- 구 id는 날짜가 붙은 기록(ADR 본문·계획·로그)과 팔 단위 이름에는 남는다.
- 시험: 별칭 해석·peers 별칭·마이그레이션 멱등성·정지 ingress 정규화(`test_control_unit_identifier_rename.py`)와 기존 관제 단위 시험의 기대값 교체.
