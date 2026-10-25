## D-883 Monitoring 호스트 자원 감시와 시험 PC 저장소 정리 요청 (D-876 §5·D-524 보충)

**Status:** Accepted for implementation (2026-10-26, 사용자 결정 3건: 외부 exporter 없이 host-guard 확장, 시험 PC 포함, 화면의 정리 요청). D-876 §4·§5와 D-524 동작 목록을 보충한다. 장치·현장 수용을 뜻하지 않는다.

### Context

2026-10-26 AI PC 디스크가 100% 찬 상태에서 시험이 계속 배치됐고, SQLite fsync 지연이 시간 시험 실패로 보였다. 시험 PC 정리는 rosy-ops `rosy-test-storage.timer`가 6시간마다 하지만, 차는 속도가 더 빠르면 사람이 알아차릴 때까지 아무 화면에도 나타나지 않는다. host-guard의 `health`는 메모리·부하·유닛만 보고, D-876 Monitoring은 그 보고를 원천으로 읽는다. D-876 §5는 Monitoring이 조치를 직접 실행하지 않는다고 정했다.

### Decision

1. **수집:** `rosy-host-guard-remote health`가 기존 필드 뒤에 `~/rosy-test`(없으면 홈)와 `/`의 여유 용량·사용률, `nvidia-smi`가 있을 때 GPU 메모리를 덧붙인다. 사이트 guard는 이를 `status.json`의 `resources`에 기록한다. Prometheus exporter·Grafana는 설치하지 않는다(D-876 §4 유지).
2. **판정:** 여유 30GiB 미만 또는 사용률 90% 이상이면 `disk-low`로 보고한다. 기준은 rosy-ops 시험 저장소 운영 규칙과 같다. 디스크 부족은 보고 전용이며 restart·reboot 단계를 진행시키지 않는다. 재부팅은 디스크를 비우지 않는다. 값을 보내지 않는 예전 PC는 확인 불가이며 정상으로 표시하지 않는다.
3. **대상:** 모델 PC·AI PC도 Monitoring 대상이다. guard에 등록된 PC는 역할과 관계없이 자원을 보고한다.
4. **정리 요청:** D-524 Service Control에 `clean-storage` 동작을 추가한다. ai·model 역할만 허용하고 site는 거부한다(제품 DB·장치 보정이 있다). 동작은 해당 PC의 기존 `rosy-test-storage.service`를 한 번 시작하는 것뿐이다. 무엇을 지우고 무엇을 보존하는지, busy 잠금과 사용 중 환경 보호는 rosy-ops `host_storage.py`가 소유한다. Fleet 응답은 요청 수락까지만 뜻하고, 회수 결과는 다음 guard 보고의 여유 용량으로 확인한다.
5. **화면과 권한 (D-876 §5 보충):** Monitoring 화면은 기존 D-524 경로(`POST /api/fleet/hosts/{host}/control`, 기명 operator, `operator_confirmed`, 감사 기록)를 호출하는 버튼만 둘 수 있다. Monitoring 수집 자격은 계속 읽기 전용이며 제어 자격을 받지 않는다. Fleet이 꺼져 있으면 버튼을 쓰지 않고 수동 명령을 안내한다. 재시작·재부팅·네트워크·안전 해제를 Monitoring에 추가하지 않는다.

### Alternatives

| 대안 | 판단 |
|---|---|
| node_exporter·GPU exporter 설치 | 지표는 풍부하지만 PC마다 설치·포트·인증 관리가 생긴다. 필요한 값은 기존 forced command로 충분하다 |
| Prometheus·Grafana 경보 | D-876이 첫 범위에서 제외했다. 수집·조회가 외부 도구 가용성에 묶인다 |
| Monitoring이 SSH로 직접 정리 | 읽기 전용 수집기에 제어 자격이 들어가고 감사 경로가 둘이 된다 |

### Consequences

디스크 부족이 최대 10분 안에 상태 화면과 Fleet 호스트 조회에 나타난다. guard-remote·helper를 바꿨으므로 각 PC에 재설치해야 새 값과 동작이 생긴다. 재설치 전 PC는 확인 불가로 보이고 `clean-storage`는 helper가 거부한다.

### Related decisions

- D-524: Service Control의 닫힌 동작 집합에 `clean-storage`를 더한다.
- D-530: host-guard 복구 단계는 바꾸지 않는다.
- D-876: §4(도구)는 유지하고 §5(조치)를 위 5번으로 보충한다.
