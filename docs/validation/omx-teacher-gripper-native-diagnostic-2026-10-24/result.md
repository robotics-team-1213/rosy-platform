# 그리퍼 진단 보완의 실제 native 실행 증거

2026-10-24 KST. 실제 코드 source는 `commit 8d119665da8fae004499d22c432eefd80bff57b3`이며 로컬 main의 ancestor다. 공개 push나 원격 CI 결과를 뜻하지 않는다.

기존 실패와 진단 보완 시험은 [10월23일 결과](../omx-teacher-gripper-observation-2026-10-23/result.md)와 [시험 기록](../omx-teacher-gripper-observation-2026-10-23/verification.md)에 있다. 그 기록은 동결 상태로 유지하며, 이 문서는 이후 실행을 추가한다.

## 공식 착지와 코드 바이트

공식 착지57107은 종료0이었다. guard273개와 변경 영향 시험490개가 통과했고 NEW0이었다. 공통 착지 receipt SHA256은 `cf46eb3ba29c3a91191f0a71fc34d1d224f96a95becaff91a027f8a9dfd5d935`다. 앞선 전체 루트 실행의 실패가 사라졌다고 주장하는 전체 재시험 결과는 아니다.

| 구분 | 원본 근거 |
|---|---|
| 착지 guard 로그 | 12,589바이트, sha256:81cd120df98fa42156cf42495dcf75168ff9863eb1544c4fb2be1103ac68bde6 |
| 착지 영향 시험 로그 | 11,733바이트, sha256:2518e6f2262496f9fe6ba19ccb817ed9b0edc11568f7f3606a61b589d2f6b6c6 |
| 실제 teacher 바이트 | sha256:4529d262079713e704660eb03c2c00294acf3973aaef897c95a0c6f4646e01dc |
| 실제 진단 serializer 바이트 | sha256:66f8fc7bd722c711456103e2b3d138813b4f1fedb091b0b4e3f9b0c6e9129987 |

해당 commit의 착지 receipt는 공통 Git 디렉터리의 `rosy-land/8d119665da8fae004499d22c432eefd80bff57b3.json`, 로그는 OS 임시 디렉터리의 `rosy-land/fix-omx-gripper-failure-evidence/` 아래 `run-g1-1.txt`와 `run-1-1.txt`다. source·receipt·실제 로그 바이트를 독립 검토가 대조했다.

## 단 한 번의 진단 실행

Native run (source revision + nonce): `8d119665da8fae004499d22c432eefd80bff57b3-a33a1fd57987`.

2026-10-23T15:09:52.856511UTC에 같은 준비 identity를 단 한 번 시작했다. 시작 전30초 간격의 두 읽기 전용 관측 모두 예약분을 반영한18CPU/12.7609GiB 여유를 확인했다. 원래 native6CPU/8GiB 시작 검사,4CPU/4GiB 격리, 교사 목표·그리퍼 판정·freshness 기준을 유지했다. 동시 동료 pytest를 중단하거나 검사를 우회하지 않았다.

EXITED0/PASS3회였다. 각 capture는 complete·issues 없음이며 teacher success=true, error·watchdog·실패 근거 필드는 null이었다.

| 순서 | episode ID | RGB 프레임 |
|---|---|---:|
| 1 | 4d678edb-342f-4552-8e6e-1b3d69a6029a | 1,586 |
| 2 | efcbe10e-9f90-4b65-b18a-85f07c3201e6 | 1,585 |
| 3 | cd7fad03-f490-4982-a45c-1138d650916c | 1,586 |

세 에피소드의 process-cleanup은 verified_absent=true·remaining_groups=[]다. 최종 서비스는 inactive/dead·MainPID0·ExecMainStatus0·ControlGroup 빈 문자열, 정확한 cgroup과 budget.lock/budget.resv는 부재였다.

## 원본 무결성과 재검토

| 증거 | SHA256 |
|---|---|
| native archive43,455,271바이트 | sha256:e2b60d18f20df5c26bf87ecc8f6d30b3d2488400ce5db21d5bc7d1b835d7bbc0 |
| extraction map | sha256:7ca98941df702a0d59a981da4294efa7d871d9aade60b54580ce920533d1bd7a |
| 실제 source inventory | sha256:fbef54ebb170ffd2490b704757e6ae0ae5e6544eb107057b6d479a164fac86f1 |
| dependency inventory | sha256:b8e5c71b6c03419dcb29e8bde930b1dd8f24028abad3debada61f0eafdce0b8d |
| verification.json | sha256:fc802c4229815aea59500129731c3a628c8e327264f816ceca5075157aa4e6d7 |

소유 scratch `C:/DevTemp/learning-execution-20261023/teacher-gripper-native-diagnostic-once/`에 receipt·archive·map·회수 파일을 보존했다. Windows 추출 별칭은 map으로 해석하고 전체4,889파일·비압축79,271,631바이트를 archive와 대조했다. 독립 검토가 해당 바이트·source·dependency·정리를 다시 확인했다. fetch의 `OBSERVATION_NOT_ATOMIC` 경계는 그대로다.

## 이 결과가 해결하지 않은 범위

거부는 재현되지 않았다. 새 실패 handler가 native 거부에서 실행됐거나 과거 held/stale의 물리 원인이 해결됐다는 근거가 아니다. 기존 두 HOLD cohort는 각각9완료/1실패/15미실행 및20완료/1불완전 녹화/나머지미실행 상태와 원래 해시를 유지한다. 진단3개도 모든 학습 split에서 영구 제외한다. 이 결과는 실제 정책 학습·독립 정책 성공률·장치 수용·Hub 전달을 증명하지 않는다.

CE: 미해결 — 성공 경로와 정리·자료 무결성은 확인했으나 과거 실패의 물리 원인을 규명하거나 고치지는 못했다.
