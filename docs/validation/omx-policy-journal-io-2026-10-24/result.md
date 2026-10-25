# OMX 정책 저널 I/O 귀속 진단

2026-10-24, AI 검사 PC의 별도 scratch에서 실제 기록을 재생했다. 한 generic durable worker가 종료0으로 네 조건을 모두 마쳤다. **정책 episode·optimizer·formal·실물 동작은 각각0회**다. 기존 [관절 추종 진단](../omx-policy-controller-tracking-2026-10-24/result.md)의 HOLD와 원래 JTC 허용오차 실패는 보존한다.

## 범위와 실행

- API source: `bbf2af074bb7b652dc6d6c0e59c4de982d341fdf`; `policy_journal.py` SHA256 `969847c81495441479f99a88741a533e48b524f79919e7af05ea901dffa7d33b`.
- 실행 commit `bbf2af074b`: 외부 scratch의 `launch.py run` → `python tools/remote/remote_sim.py --host ai --sha bbf2af074b --durable --minutes 15 --log-dir <scratch>/remote cmd -- <고정 python3 명령>`. 정확한 full revision argv와 내장 worker/manifest는 `execution.json`에 보존했다.
- AI4CPU/4GiB·nice10·15분, worker600초·최대4회. 승인된 generic transport의 빌드·격리·자원 예약을 사용했고 ROS 노드·owner·물리 엔진·ML을 시작하지 않았다. Python3.12.3/SQLite3.45.1, 원본·측정 폴더의 filesystem device가 같았다.
- 원본 SQLite45,989,888바이트는 immutable 읽기 전용이다. 독점 생성한 복사본에서 commands/events만 비우고 source1건/파일9개를 보존했다. 기존 typed `prepare/observe/read`와 WAL/FULL·BEGIN IMMEDIATE·commit·검증을 그대로 사용했다.
- 순서는 serial/threaded/threaded/serial. threaded는 실제 두 thread의 호출 시각·순서와 prepare/이전 terminal의 인과관계를 따른다. 대기로 늦어진 실제 시작·dependency wait도 기록했다. 당시 부하·캐시·정확한 스케줄을 재현했다고 주장하지 않는다.

## 관측값

각 조건은 prepare42·observe702·read1652, 총2,396 API 호출과18,427 SQLite 측정을 포함한다. API 최대 시간은 dependency 대기 이후부터 반환까지이며 계측 오버헤드를 포함한다.

| 조건 | prepare 중앙값 ms | prepare 최대 ms | 마지막 prepare ms | 모든 API 최대 ms |
|---|---:|---:|---:|---:|
| 0 serial | 2.7381065 | 6.213966 | 2.690726 | 19.494416 |
| 1 threaded | 5.253630 | 3318.251070 | 4.483370 | 3318.251070 |
| 2 threaded | 6.1978495 | 129.538055 | 94.357268 | 148.566477 |
| 3 serial | 2.145929 | 13.299631 | 2.267120 | 89.682621 |

조건1의 가장 느린 prepare에서 `commit()`3276.184231ms, `BEGIN IMMEDIATE`0.010578ms, 두 번째 connection의 `close()`40.278940ms였다. 이 측정의 지연을 BEGIN writer 획득 대기로 설명할 근거는 없다. commit wall time에는 스케줄 지연 등이 포함되므로 순수 fsync 비용으로 해석하지 않는다. `Connection.execute` 반환 뒤 cursor fetch/iteration/decoding은 API 잔여 시간에 남는다.

**원래733.730505ms와 동일 원인을 증명하지 않는다.** 당시 최종 prepare와 겹친 다른 기록된 journal API는 없었고 마지막 observe 반환도877.972437ms 앞섰다. 원래 lease 만료 후 제출을 막은 guard는 올바른 HOLD다. 이번 측정은 새 모델 평가·정책 성공·원래 물리 실패의 재현이 아니다.

회수한 각 DB의 전체 네 테이블 fingerprint가 원본과 같음을 독립 재계산했다: intents42·accepted41·terminal41·events702·source1·source files9, 마지막 goal NULL1개. 각 DB는 WAL header와 integrity_check=ok이며 동일 SHA256 `fe93eafd312c28629795ebaf930a12491b2cff2cadf571f182c50da93a0a017f`다. 원본3파일의 해시도 종료 뒤 동일하다. 회수110파일·202,128,822바이트를 확인했다.

## 후속 수정의 경계

현재 prepare는 session lock과 stop-fence lock 안에서 수행된다. session lock만 일시 해제하면 renew/poll의 fence 대기와 submit의 session 재획득이 역순이 되어 교착할 수 있다. 이 진단에서는 권한 코드·내구성·TTL·500ms 관측/행동 freshness·안전 제한을 변경하지 않았다.

가용성 수정을 하려면 durable intent I/O를 두 임계구역 밖으로 분리하고 동일 session 제출의 추월을 막아야 한다. 이후 기존 lock 순서로 재진입해 전체 authority·lease·source·camera·freshness를 다시 검증하는 설계와 결정적 경합 회귀가 필요하다. 갱신이 가능해져도 장시간 쓰기 뒤 낡은 candidate는 원래 기준으로 거부해야 하며 자동 재시도·성공 보장의 근거가 아니다.

## 증거와 종료

Raw 기준 경로는 외부 scratch `journal-io-attribution-20261024/`다. manifest의12개 local pins·고정 원본3SHA·정확한 커맨드를 실행 전 독립 검토했다. 실제 DB·phase 수치·원본 불변·종료도 독립 검토에서 Important 지적이 없었다.

| 파일 | SHA-256 |
|---|---|
| `manifest.json` | `sha256:1ccf62222b3d3a27600320b9cf20331e67d0cef0a373068a433d9f5a10696f17` |
| `worker.py` | `sha256:52d17f7949d986c879be2b9fb77c61af58c8284b2974f40b5f7b22f95e012a23` |
| `execution.json` | `sha256:b2bf13daad8ff1d3bcf44730201b9e018a18184b26883d5e9177da2bd752692d` |
| `remote/out/journal-profile/result.json` | `sha256:2f2cad350e810bbaedfb276633feb52aef00eeeeb923c330df614db0755b34e7` |
| `remote/out/journal-profile/1/result.json` | `sha256:c59c50eea7b95f1bb686b5e60391cfc1ece8c381767e2b0683c4c1a6ca8413c2` |
| `remote/remote-run.json` | `sha256:ce6b0d2a704720fc3ca396608aef2ff839e861f030f3e3a7924872a3985e9e5b` |
| `closure-final.json` | `sha256:e7edde9698654fd36def6ff253f971cc427b8238b8d9a3cbc9f41712b190826b` |

`0.rc=0`·원래 PID 부재·scope inactive/dead·빈 ControlGroup·lock/reservation 부재·회수 후 해당 remote source/OUT 삭제를 확인했다. 영속 job journal은 보존돼 있다.

CE: 미해결 — 지연 구간을 관측했으나 원래 지연·추종 실패의 원인 해결이나 정책 수용을 검증하지 않았다. 해결 교훈은 만들지 않고 검증 기록과 후속 조건만 남긴다.
