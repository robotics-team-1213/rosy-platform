# OMX 구역 점유: 중단·불확실한 park·저장 동기화 실패 회귀

2026-11-04 host 검증 기록이다. 실물 동작·전원 차단·배포 수용은 하지 않았다.

## 검증 범위

`HOLD`와 비어 있는 session lock만으로 상대 팔 쪽 진입을 허용하던 조건은 철회했다.
HOLD는 팔이 뻗은 채 끝난 고장에도 남으므로 물리 이격을 증명하지 않는다. 현재 코드는 상대 팔
쪽 진입을 거부하고, 상대 HOLD가 있으면 중앙도 거부한다. `zone.takeover`는 설정 호환용이며
값 1로 이 조건을 완화할 수 없다.

구역 파일에 검증 operating profile과 session의 점유 기록을 쓴다. `flock` 해제만으로 기록을
지우지 않는다. 기록 파일을 fsync한 뒤 containing directory부터 filesystem root까지 차례로
동기화하므로 새 중첩 디렉터리의 이름도 이동 허용 전에 보존한다. 동기화 실패는 기록을 남기고
이동 명령을 보내기 전에 예외로 중단한다.

## 원격 RED와 GREEN

모두 `tools/remote/remote_pytest.py`가 커밋을 모델 PC에서 실행했다. 로그마다
`test/known_failures.py`를 적용했다. 운영자 PC 로그 위치는
`%TEMP%/rosy-incident-zone-durability-20261104/`이다.

| 커밋 | 로그 | 관측 |
|---|---|---|
| `cb1b96e77be6` | `red/run-1.txt` | 5 failed, 1 passed. 디렉터리 fsync 순서 및 해당 지점 오류 주입이 NEW 5건으로 재현됨. 파일 fsync 오류는 이미 이동을 막았음 |
| `190ce99d1e91` | `green/run-1.txt` | 231 passed, skipped 0. known_failures: new/known/flaky 모두 0 |

GREEN 대상은 `test/test_omx_cell_zones.py`, `test/test_omx_cell_envelope.py`,
`test/test_omx_chunk_runner.py`, `test/test_omx_cell_auto_pick.py`,
`test/test_omx_cell_params.py`, `test/test_omx_hotfix.py`다.

순서 시험은 새 중첩 경로에서 파일과 모든 상위 디렉터리의 fsync가 끝나기 전에는 점유가
admitted로 기록되지 않음을 검사한다. 파일·구역 디렉터리·새 상위 디렉터리·기존 상위 경로의
fsync 실패를 주입하면 reach를 보내지 않고 점유를 남기는지도 검사한다. 같은 suite는 실제
`Runner.tick`의 park timeout(`ok=true`, `settled=false`), 잘못된 home·비유한 관절,
stale/다른 session 응답, 프로세스 종료, 외부 owner·손상 기록의 해제 거부를 확인한다.

## 배포와 복구의 제한

옛 reader는 파일 내용 없이 OS lock만 확인하므로 새 reader와 혼용할 수 없다. 기존 세션을
안전하게 끝내고 실제 구역 이격을 확인한 상태에서 모든 팔의 공유 runtime을 함께 갱신해야 한다.
빈 옛 lock 파일 자체는 이격의 증거가 아니다.

복구는 기존 사람 감독 절차로 중단한 팔의 자세를 회복한 뒤, 같은 검증 owner의 Gate가 보내는
guarded park의 새 응답을 사용한다. 현재 session과 일치하고 오류 없이 settled이며 유한한
몸체 관절이 loaded home 오차 안일 때만 그 owner의 기록을 비운다. 외부·손상 기록은 계속
막는다. 파일 삭제·profile 변경에 의한 채택·force-clear 경로를 추가하지 않았다. Fleet 사건
HOLD의 사람 확인과 해제는 별도다.

실제 저장장치의 전원 손실 보존, OS 재시작, 혼합 버전 배포, 실물 양팔 구역 수용은 이
host 시험이 증명하지 않는다. 운영 절차는 [OMX README](../../../deploy/robot/omx/README.md)의
「양팔 구역 점유와 중단 복구」를 따른다.
