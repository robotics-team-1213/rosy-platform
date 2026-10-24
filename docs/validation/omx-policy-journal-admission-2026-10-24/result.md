# OMX 저널 쓰기 중 권한 점검 가용성 수정

2026-10-24. [기존 I/O 진단](../omx-policy-journal-io-2026-10-24/result.md)에서 확인한 잠금 경로를 수정했다. **학습·실제 모델 작업 평가·formal·실물 동작은 추가하지 않았다.** 기존 정책 평가 HOLD와 원래 추종 실패 기록은 보존한다.

## 변경과 경계

구현 commit `2c47808edcf1e102a58f8a8aa2e4131406e3e245`. `OwnerPolicySession.submit`은 pending 제출만 별도 lock으로 직렬화하고, 기존 session 안에서 검증한 candidate·command·lease를 바꾸지 않고 보존한다. durable `journal.prepare` 동안 session과 stop-fence 잠금을 모두 놓는다. observe/poll/renew/stop은 submit 전용 lock을 획득하지 않는다.

commit 뒤 session→stop-fence 순서로 재진입해 authority/install/owner/lease/stop/source/camera/freshness를 다시 검사한다. runtime 재연결이나 lease ID·episode·identity 변경을 거부한다. 원래 기록된 grant와 현재 lease가 모두 유효해야 하며 native runtime의 전송 전후 검사에도 두 유효기간을 적용했다. 만료된 intent를 갱신으로 되살리지 않는다.

SQLite WAL/FULL·schema·durable intent·TTL·기존 입력 시간 예산은 그대로다. callback sink는 commit 뒤에만 등록한다. 전송 전 실패는 미사용 sink를 해제하고, 전송을 시작해 결과가 불명확하면 원래 늦은 goal/cancel 응답을 받을 sink를 보존한다. 저장 실패와 중간 HOLD는 제출을 막으며 자동 재시도·rearm은 없다. 오래된 candidate는 여전히 HOLD해야 하므로 이번 변경이 느린 쓰기 뒤 작업 성공을 보장하지 않는다.

## 실행한 시험

외부 raw 경로는 `C:/DevTemp/learning-execution-20261023/journal-admission-20261024/`다. 모든 pytest와 ROS 실행은 승인된 원격 검사 PC에서 했다.

| 단계 | commit | 관측 |
|---|---|---|
| RED 경합 | `4110b63153` | Event로 prepare를 멈추자 renew/poll/observe/stop 및 갱신 경로5건이 완료되지 않아 실패. pending 제출 추월 방지1건은 통과 |
| RED 전송 중 grant | `7c5abffeff` | 현재 lease를 갱신한 뒤 원래 grant가 전송 중 만료돼도 PermissionError가 나지 않아 실패 |
| GREEN host | `2c47808edc` | local 모듈 전체·SIM runtime·정책 구성 검사에312개 통과 점, F/E0·runner종료0·known comparator NEW0/known0/flaky0 |
| 별도 Jazzy ROS | `2c47808edc` | 실제 action server 전송·철회와 setup cleanup6개 통과/1.36초·runner종료0 |

Host 명령: `python tools/remote/remote_pytest.py --log-dir <raw>/green -- middleware/robot_execution/local/test test/test_omx_sim_policy_runtime.py test/architecture/test_omx_policy_config.py -q`. 요약이 억제된 로그라 module-level ROS skip 수를 확정하지 않았고 host 실행을 ROS 수용으로 계산하지 않는다.

별도 ROS 명령: `python tools/remote/remote_sim.py --host ai --sha 2c47808edc --durable --minutes 15 --log-dir <raw>/ros cmd -- <명령>`. 명령은 `env ROS_DOMAIN_ID=199 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST python3 -m pytest middleware/robot_execution/local/test/test_policy_runtime_ros.py --basetemp "$OUT/pytest-tmp" -q -pno:launch_testing -pno:launch_ros`다. AI4CPU/4GiB·nice10·15분, 별도 domain/고유 이름의 테스트 action server만 사용했다.

이 ROS fixture는 기존2초 source/joint·12초 lease의 합성 policy/authority이며 실제 ACT 모델을 로드하지 않는다. 4개 goal 사례의 SQLite와 저장된 receipt를 대조했다. 정상2개는 accepted→status4, 철회2개는 accepted→cancel ACK→status5다. 부모 연동 fixture 두 개의 초기 receipt UNKNOWN과 최종 SUCCEEDED/FAILED는 해당 임시 evidence 경로의 관측이며 live Fleet 수신·승격·task 성공을 뜻하지 않는다. 나머지2개는 주입한 CPU setup 실패를 보존하면서 cleanup 오류가 없는 시험이다.

4개 goal 사례 모두 executor/workers 종료·spinner 부재·남은 thread stack 없음·원래 예외 없음이다. 회수164파일·5,978,137바이트와 durable actor의 rc0·원래 PID 부재·inactive/dead·빈 cgroup·lock/reservation 부재·회수 후 해당 source/OUT 삭제를 확인했다. 독립 검토가 실제 DB/event/receipt·수치·binding/closure를 재확인했다.

## 증거 지문

| 파일 | SHA-256 |
|---|---|
| `red/run-1.txt` | `sha256:a7269fd6f09b3f0ace4e28941ce29d36e6d9e28b584abe659e5516bf37f584fb` |
| `red-native-grant/run-1.txt` | `sha256:80aaf32dfa20eda2ccc7c2c85dc8d11ca5599a8b647afb56d5745ad7b8520fc8` |
| `green/run-1.txt` | `sha256:93d7685df8931543a1f6a3bb25d551ff67633cbb5b6600b5919284462b0b011a` |
| `ros/run.txt` | `sha256:cb78c764e5fd95417e55487109b237bb527dbdfbbd29fad5312d6da39b5bfd41` |
| `ros/remote-run.json` | `sha256:77214c274f4743f9d4dd49930172c216b50ccc50779fcc78ad9c0b5fb06a8cad` |
| `ros-closure.json` | `sha256:27f3ddd2af3d1a9cd0e954abb6f23f48f9573974578fe6405903467ad74710a6` |

CE: 해당 없음 — 잠금 순서·원래 grant 보존과 후속 검사는 최종 코드·Event 회귀·local README에서 복구할 수 있어 별도 해결 교훈을 늘리지 않았다. 기존 정책 HOLD·과거 I/O 지연의 정확한 원인·원래 JTC 추종 실패는 미해결이다. 이 시험은 production 시간 예산의 가용성·정책 품질·HF·실물/양팔 수용을 증명하지 않는다.
