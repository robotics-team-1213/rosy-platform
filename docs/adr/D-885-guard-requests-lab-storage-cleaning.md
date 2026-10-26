## D-885 guard가 디스크 부족 시험 PC의 저장소 정리를 요청한다 (D-883 보충)

**Status:** Accepted for implementation (2026-10-26, 사용자 지시: 디스크 문제가 앞으로도 계속 처리되어야 한다). D-883 §2의 "디스크 부족은 보고 전용"을 시험 PC에 한해 보충한다. 장치·현장 수용을 뜻하지 않는다.

### Context

2026-10-26 AI PC는 venv 97개(56GB)가 48시간 보존 규칙 안에 있어 정리 서비스가 지울 것이 없었다. 사람이 버튼을 누르기 전까지는 디스크가 계속 찼다. D-883은 guard가 `disk-low`를 보고만 하고 운영자가 Fleet에서 `clean-storage`를 요청하게 했다. 관제 PC 자신은 guard의 `health`를 받지 않아 디스크·RAM·GPU 여유가 보이지 않았다.

### Decision

1. guard가 `ai`·`model` 항목의 `disk-low`를 보면 그 PC의 강제 명령 `clean-storage`를 한 번 요청한다. 강제 명령은 D-524 helper(`sudo -n rosy-host-control clean-storage`)로만 실행한다. 무엇을 지우고 무엇을 남길지는 계속 rosy-ops `host_storage.py`가 정한다.
2. 같은 PC에 대한 요청은 `GUARD_CLEAN_GAP_S`(기본 6시간)마다 한 번이다. 거절도 같은 간격을 기다린다. 요청과 거절은 `actions.jsonl`에, 마지막 요청 시각은 `status.json`의 `last_clean_request`에 남는다. 디스크 부족은 계속 restart·reboot 단계를 진행시키지 않는다.
3. 관제 PC와 guard 목록 밖의 PC에는 요청하지 않는다. 관제 PC에는 제품 DB와 장치 보정이 있다.
4. 관제 PC의 자기 행은 같은 강제 명령을 로컬에서 실행해 `resources`에 디스크·RAM·GPU·CPU 값을 더한다. 실패하거나 응답이 깨지면 기존 복구 보고 값만 남기고 정상 값을 만들지 않는다.
5. `/etc/rosy/host-control/units-user`를 ai·model의 desired state(`approval=recovery`, `@LOGIN@`)로 관리한다. 빠지면 30분 점검이 드리프트로 보고한다.

### Alternatives

| 대안 | 판단 |
|---|---|
| 운영자 버튼만 유지 | 밤사이 디스크가 차도 사람이 볼 때까지 처리되지 않는다 |
| 정리 서비스 주기를 1시간으로 단축 | 디스크가 차지 않아도 매번 프로세스 검사와 대기가 생긴다. 부족할 때만 요청하는 쪽이 부담이 작다 |
| guard가 직접 파일을 지움 | 보존 규칙이 두 곳에 생기고 guard 키에 삭제 권한이 생긴다 |

### Consequences

guard 강제 명령이 하나 늘었다. 각 PC에 guard-remote를 재설치해야 요청이 받아들여지고, 재설치 전에는 6시간마다 거절 한 줄이 기록된다. 정리 결과는 다음 guard 보고의 디스크 값으로 확인한다.

### Related decisions

- D-524: helper의 닫힌 동작 집합(`clean-storage`)을 그대로 쓴다.
- D-530: host-guard 복구 단계와 desired state 방식을 유지한다.
- D-883: 수집·판정·버튼은 그대로이고 §2만 시험 PC에 한해 보충한다.
