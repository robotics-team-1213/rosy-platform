## D-991 PC 정비는 Fleet 안의 화면으로 나누고, 재부팅해도 되는지는 그 PC의 도우미가 판단한다

**Status:** Accepted (2026-11-07, 사용자 결정: "monitoring에서 PC 유지보수도 가능하게", "바로 처리"). 결정 1·2·4·5·6(CLI)은 도우미·API·호스트 서비스 화면·`tools/remote/host_ops.py`로 구현했다. 접속 불가 알림과 결정 3의 화면도 구현했다. 각 PC 재설치와 실물 확인은 하지 않았다.

관계: [D-524](D-524-service-control.md)(Service Control, 재부팅 항목을 보충), [D-530](D-530-host-management-desired-state-and-guard.md)(guard 복구 단계), [D-876](D-876-rosy-monitoring-independent-site-and-aggregate.md)·[D-883](D-883-monitoring-host-resources-and-storage-clean.md)(Monitoring 읽기 전용, 조치는 D-524), [D-937](D-937-product-app-entry-grammar.md)(제품 입사 문법), D-988(로봇 유지보수 상태, Proposed, 착지 전), [D-871](D-871-auto-update-every-host-service-and-update-view.md)(중앙→현장→기기).

### Context

- 사용자는 PC 유지보수를 Monitoring에 더하거나 나누자고 했다. D-876 §5와 D-883이 Monitoring을 읽기 전용으로 정했으므로 더할 수 없다.
- PC 조치 화면은 이미 있다. Fleet `설치·보정 → 호스트 서비스`가 상태 표시, 재부팅, 유닛 재시작·정지, 저장소 정리를 한다. 설치 화면 안에 있어 평소에 찾기 어렵다.
- 2026-10-28 야간 재부팅이 팔 이동 중 Fleet PC를 재시작했고 토크가 꺼져 팔이 떨어졌다. 그때 고친 것은 야간 타이머뿐이다. 화면 버튼과 guard 복구는 같은 도우미의 `reboot`를 부르는데 세션 잠금을 보지 않았다. `shutdown -r +10`의 10분 안에 시작한 세션도 막지 못했다.
- 화면 버튼은 학습과 원격 시험이 도는 PC도 바로 예약했다. guard는 학습이 메모리를 다 먹어 멈춘 PC를 살리려고 재부팅하므로(D-530) 같은 조건으로 막을 수 없다.
- 조치 목록은 실제와 다르다. 모델 PC 유닛은 0개이고 OMX 셀 PC는 보고만 된다. AI PC 목록은 `pinky-*` 3개뿐이다.

### Decision

1. **재부팅 판단은 PC의 도우미가 한다.** 부르는 쪽이 화면이든 guard든 CLI든 같은 규칙을 받는다.

   | 도우미 동작 | 부르는 쪽 | 팔 세션 잠금 | 살아 있는 작업·busy |
   |---|---|---|---|
   | `reboot-if-free` | 화면의 `reboot` | 거절, 종료 코드 6 | 거절, 종료 코드 7 |
   | `reboot` | guard 복구, 화면의 `reboot-over-jobs` | 거절, 종료 코드 6 | 보지 않음 |

   - 작업은 `host_probe.py`가 세는 것과 같다. 이번 부팅의 `~/rosy-jobs/*.lock` 중 pid가 살아 있는 것, 만료 전 `*.resv`(Isaac 감독 실행은 이것만 쓴다), 만료 전 `busy`다.
   - 도우미는 root이고 이 파일들은 사용자 소유다. 세션 잠금은 열지 않고 `/proc/locks`에서 inode로 찾는다. FIFO가 도우미를 자기 잠금 안에서 멈추게 하면 재확인 타이머도 막히고, 잠금을 시험 삼아 잡으면 그 순간 시작하는 세션이 실패하기 때문이다. 작업 파일은 일반 파일만 앞 64바이트를 읽고 첫 단어의 숫자만 쓴다. `/proc/locks`를 못 읽으면 세션이 도는 것으로 본다.
   - 팔 세션을 넘는 동작은 없다. 사람이 확인해도 넘지 못한다.
   - 예약 때 도우미가 570초 뒤의 `recheck-reboot` 타이머를 먼저 건다. 그때 세션이 잡혀 있으면 자기가 예약한 재부팅만 취소한다. 타이머를 못 걸면 재부팅을 예약하지 않는다. 마지막 30초 안에 시작한 세션은 막지 못한다. `shutdown`이 5분 전부터 새 로그인을 막으므로 그 뒤 원격으로 새로 시작하기는 어렵지만, 이미 로그인한 사람은 시작할 수 있다.
   - `recheck-reboot`는 강제 명령 키로 부를 수 없다.
2. **작업을 넘는 재부팅은 사람의 두 번째 요청이다.** `reboot`가 409 `HOST_JOBS_ACTIVE`이면 화면이 무엇이 끊기는지 묻고, 확인하면 `reboot-over-jobs`를 보낸다. 팔 세션은 409 `ARM_SESSION_ACTIVE`로 끝난다.
3. **역할을 셋으로 나눈다. 새 서비스와 새 제품 앱은 만들지 않는다.** PC 정비 화면은 자기 서비스 없이 Fleet API만 부르므로 D-937의 네 제품 원형에 들지 않는다.

   | 역할 | 맡는 일 | 위치 |
   |---|---|---|
   | Monitoring | 관측. 조치 버튼 없이 PC 정비로 가는 링크만 | `applications/monitoring` |
   | PC 정비 (`Rosy Fleet — PC 정비`) | PC 조치와 결과 | `/console/maintenance`, `applications/fleet/web/maintenance/` |
   | 로봇 유지보수 | 로봇을 작업에서 빼기 | D-988, 관제의 로봇 카드 |

   레일에는 넣지 않는다. 소수가 가끔 쓰는 일이고 D-961의 다섯 영역을 늘릴 근거가 아직 없다. Monitoring의 PC 행, 접속 불가 알림, `설치` 화면에서 들어온다. 자주 쓰게 되면 그때 올린다.
4. **`DeviceCareStore`는 합치지 않는다.** 기록은 명령 권한이 없고, D-988 플래그는 admission 입력이며, D-524는 실행 경로다. 이름도 바꾸지 않는다. 화면 말은 `정비`, 코드 말은 `care`(기록), `maintenance`(로봇 상태), `host control`(PC 조치)이다. PC 조치 이력은 `fleet_device_care_events`에 `host:<PC>` 항목으로 함께 남긴다. D-988도 같은 표에 쓰므로 같은 형식으로 읽는다. 기록소가 없거나 쓰기가 실패해도 조치 응답은 바뀌지 않는다. CLI 조치는 Fleet이 없을 때 쓰므로 PC의 journal에만 남는다.
5. **PC는 역할 하나로 보지 않는다.** 관제 PC는 Fleet과 OMX 셀을 함께 돌리고, 모델 PC는 학습·검수·시험과 임시 Harbor를 돌린다. `deploy/hosts/services.yaml`에 `operator_restart`로 표시한 유닛만 재시작할 수 있고, 시험이 Fleet 목록·도우미와 맞춘다. 유닛 정지는 없앤다. 관제 PC의 셀 카메라 유닛은 도우미가 팔 세션 중 거절한다. 관측기와 관측 브리지는 토크 상태까지 봐야 하므로(D-871) 넣지 않는다. `pinky-*`는 ROSY 밖 서비스이므로 뺐다(2026-11-07 AI PC guard의 감시 목록이 비어 있음을 확인, 감시 목록에 있으면 재시작 거절이 재부팅으로 이어진다). 추가 셀 PC는 아직 없다(`omx_hosts` 비어 있음). 그런 PC가 생기면 `HOSTS`를 "PC + 역할 목록"으로 바꾼다. Harbor는 소유자가 Harbor 저장소이므로 영향 표시만 한다. 로봇은 Rosy Robot과 D-988, 개발 노트북은 대상이 아니다.
6. **Fleet이 꺼지면 CLI가 같은 도우미를 부른다.** `tools/remote/host_ops.py`가 Fleet과 같은 목록으로 수동 명령 안내를 대신한다. 관제 PC가 현장 관제 소속이 아닌 모델·AI PC까지 맡는 지금 배치는 임시이며, R이 전용 PC로 옮기면 호출 위치만 바뀐다. Fleet 없이 화면 조치가 필요해지거나 현장이 둘이 되면 독립 앱을 ADR로 다시 판단한다. 완전히 멈춘 PC는 소프트웨어로 복구할 수 없다(2026-11-07 모델 PC 6시간 정지). guard가 PC가 2번 연속(20분) 응답하지 않으면 한 번, 돌아오면 한 번 webhook으로 알린다. Fleet의 알림 경로는 로봇 사건 전용이고 Fleet이 살아 있어야 하므로 쓰지 않는다. `/etc/rosy/host-guard/alert-webhook`(guard 계정 0600)이 없으면 알리지 않는다. 2026-11-07 확인: 이 파일은 없고, 모델 PC에 역방향 guard도 설치되어 있지 않아 관제 PC를 감시하는 쪽이 없다. 원격 전원 장치와 함께 사용자 결정 대기다.

### Alternatives

| 대안 | 판단 |
|---|---|
| Monitoring에 조치 추가 | D-876 §5·D-883과 충돌한다. 수집 자격에 제어 권한이 들어가고 감사 경로가 둘이 된다 |
| 별도 Maintenance 앱·서비스 | Fleet이 꺼질 때만 이득인데 제어 자격과 세션, 감사가 늘어난다. CLI로 그 이득의 대부분을 얻는다 |
| Fleet 레일의 여섯째 영역 | 가끔 쓰는 일이 모든 역할의 첫 화면에 늘 보인다 |
| 판단을 Fleet에 두기 | guard와 CLI가 Fleet을 거치지 않아 같은 사고가 남는다 |
| guard도 작업 잠금에서 멈추기 | 학습이 PC를 멈춘 경우 복구가 사라진다(D-530 후퇴) |

### Consequences

- 새 도우미를 설치하기 전까지 그 PC의 화면 `reboot`는 `reboot-if-free`를 몰라 502 `HOST_HELPER_FAILED`다. 재부팅이 안 되는 쪽으로 실패한다. guard의 `reboot`는 설치 전까지 옛 동작 그대로이므로 **각 PC에 설치해야 사고 경로가 닫힌다.** 도우미는 host-state manifest의 `approval` 항목이다.
- guard는 팔 세션 동안 재부팅이 거절되며, 기존 규칙대로 거절을 기록하고 다음 점검에 다시 시도한다. 세션이 메모리를 다 먹어 PC가 멈춘 경우 복구는 하드웨어 워치독이 맡는다.
- 세션 잠금은 "세션이 돈다"는 근거이지 팔이 접혔다는 근거가 아니다. 이 규칙은 도는 세션을 끊지 않을 뿐, 잠금이 없을 때 팔이 안전하다고 주장하지 않는다.
- 호스트 pytest는 실제 재부팅·타이머·세션 수용을 대신하지 않는다.

### 기존 결정과의 관계

| 결정 | 관계 |
|---|---|
| D-427 | part와 소유 ID를 바꾸지 않는다 |
| D-429 | Fleet API와 도우미의 방향을 유지하며, 화면은 권한을 갖지 않는다 |
| D-430 | 최종 장치 권한을 바꾸지 않는다. 팔 세션을 끊는 경로 하나를 닫는다 |
