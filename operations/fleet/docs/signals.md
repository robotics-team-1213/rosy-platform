# Fleet 신호등 감독 (D-443)

Fleet은 등록된 신호등을 2 s마다 인증된 `/status` 요청으로 감독한다. 콘솔이 열려 있지 않아도 Fleet 프로세스가 실행되는 동안 감독한다. 장치의 heartbeat 상실 시 failsafe는 펌웨어가 소유하며 Fleet을 대신하는 안전 회로가 아니다.

수동 점등은 인증된 operator가 콘솔에 있는 동안만 유지된다. 콘솔은 보이는 화면에서만 다음 presence 요청을 보낸다. viewer의 상태 조회는 presence가 아니다.

수동 명령과 presence에는 공유 `--token` 또는 `site_users` operator 자격증명 설정이 필요하다. 기존 loopback 개발 모드의 익명 operator는 인증된 presence로 세지 않는다.

| API | 역할 | 결과 |
|---|---|---|
| `POST /api/fleet/signals/presence` | operator | `{ "present": true }`. 인증 principal의 서버 단조 시각을 갱신하며, 신호등이 없으면 `NO_SIGNALS` |
| `POST /api/fleet/signals/{signal_id}/command` | operator | 기존 wire 명령. 감독자가 seq를 채우며 수동 명령은 그 operator의 presence를 시작한다 |
| `GET /api/fleet/signals`, `GET /api/fleet/state` | viewer 이상 | 상태 캐시와 evidence. presence는 갱신하지 않는다 |

presence가 10 s 이상 끊기면 수동 점등을 적색 점멸(`flash_red`)로 전환한다. 자동 cycle로 돌아가지 않는다. Fleet 재시작 뒤 이미 수동 점등인 장치도 소유자 기록이 없으면 점멸로 만든다. 다시 점등하려면 운영자가 새 명령을 내려야 한다.

장치의 인증 접촉이 한 번이라도 10 s 이상 끊긴 의도는 stale이다. 링크나 presence가 돌아와도 되살리지 않는다. 끊김 없이 감독하던 장치가 failsafe에 들어온 경우에만 마지막 의도를 한 번 재단언할 수 있다. 승인 후보 fence가 있는 의도와 `stale_seq` 불일치 중인 의도는 재단언하지 않는다.

seq는 `max(감독자 seq, 장치 seq)`로 매번 맞춘다. 409 `stale_seq` 뒤 자동으로 한 번 재시도할 수 있는 명령은 `all_red`·`flash_red`뿐이다. cycle·hold·manual은 자동 재시도하지 않는다. 실패가 계속되면 행의 불일치로 남는다.

상태 행의 기존 필드는 유지하며 `link`, `age_s`, `intent_age_s`, `requires_command`를 더한다. 오프라인 값은 마지막 보고이며 허가 근거가 아니다. 독립 관측이 없으면 absent, debounce 확정 전이면 pending이다. 어느 쪽도 agree가 아니다. agree 역시 녹색 허가를 뜻하지 않는다. 신호 상태를 admission에 연결하는 작업은 D-443 §1.4의 다섯 조건 모두를 검증하는 별도 변경이다.

소스·호스트 회귀만으로 장치 감독, 실제 램프, 로봇 정지를 수용하지 않는다. 첫 운영 활성화에는 실제 presence 만료·링크 단절·재시작 readback이 필요하다.
