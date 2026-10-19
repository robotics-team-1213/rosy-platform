# OMX SIM Fleet → CORE → LeRobot → Gazebo integration

2026-10-19. 사용자는 학습 checkpoint가 없으며 고정 SIM 정책으로 전체 경로부터
검증하도록 선택했다. 실물 배포 대상과 승인된 정책 revision도 없다.

## 구현과 권한

기존 Fleet의 인증된 policy state/lease HTTP를 장치 consumer가 읽고, 기존 CORE
arm port와 dedicated steady-clock OMX owner에 결속한다. SDK는 관측·목표·정지만
요청한다. 설치 pin, local AttemptIdentity, window, rig, calibration, episode와
owner session은 SDK 입력에서 받지 않는다. ROS callback은 검증된 local cache만 읽는다.

기본값은 비활성이며 SIM 설치만 허용한다. 최대 1초 lease에서 요청·readback 시간을
차감한다. lease 전에 준비한 소유 격리 subprocess를 재사용해 각 HTTP 교환을 0.2초 timeout으로 실행하고,
timeout 시 kill/reap한다. 프로세스 생성·OS scheduling의 실시간 보장은 아니다.
인증값은 stdin으로 전달하고 환경 proxy와 redirect는 차단한다. fault는 영구 폐쇄하며
stop fence를 기록한 뒤 worker 종료를 기다린다. 재접속은 rearm하지 않는다.

Fleet의 `device_delivery=not_connected`는 서버가 delivery ACK를 갖지 않는 기존 의미다.
별도의 SIM receipt가 로컬 수신을 기록한다. local SIM identity는 Fleet Mission/Action
admission이 아니며, 이 시험으로 Fleet 작업 완료를 선언하지 않는다.

## 원격 회귀 근거

로그 root: `C:/Users/SERIGGG/AppData/Local/Temp/rosy-omx-policy-chain/`.
로컬 pytest는 실행하지 않았다. 아래 pytest는 committed revision을 원격 runner로 보냈다.

| Revision | 로그 | 결과 |
|---|---|---|
| `e63904a09` | `red-reviewed-boundaries/run-1.txt` | 만료·미래 lease, 발급 후 confirmation/incident와 proxy 검사의 5 failed / 23 passed |
| `59ff40a342` | `green-reviewed-lease/run-1.txt` | 28 passed |
| `e622829278` | `green-chain-preparation/run-1.txt` | 실제 Fleet HTTP와 기존 session/runtime 회귀 134 passed |
| `39a42e94d5` | `red-total-deadline/run-1.txt` | drip 응답 timeout 실패 재현. 카메라는 잘못된 fixture digest로 실패하여 source-age RED로 사용하지 않음 |
| `87abee0f43` | `green-total-final/run-1.txt` | 136 passed / 13.30s, known-failures NEW 0 |
| `345a36df09` | `red-intake-order/run-1.txt` | source stamp·로컬 monotonic이 증가해도 source-age receipt가 역행하는 회귀 1 failed / 10 passed |
| `302614ef41` | `green-intake-final/run-1.txt` | 역행 관측 거부와 기존 owner·session·Fleet 회귀 215 passed / 26.44s |
| `004350acdf` | `red-renewal-budget/run-1.txt` | 실제 관측한 교환 지연과 고정 대기에서 1.13초에 갱신하는 실패 재현 |
| `c7792975d0` | `green-renewal-budget/run-1.txt` | 남은 예산에 따른 갱신과 만료된 old authority 거부 포함 217 passed / 13.90s |
| `d1e938320f` | `red-pinned-capture/run-1.txt` | capture context·프레임 pin·정지 접근성의 3 failed / 1 passed |
| `d10eb9e4ae` | `green-pinned-capture/run-1.txt` | 257 passed / 1 skipped / 28.69s, runner exit 0, known-failures NEW 0 |

`d10eb9e4ae`의 9개 선택은 기존 owner/intake·lease·camera·chain·session·runtime binding에
`middleware/core/api/test/test_arm_policy_api.py`와
`learning/training/omx/test/test_act_owner_capture.py`를 더한 것이다.
마지막 파일의 `test_actual_cpu_model_composition_is_numeric_only`는 torch/LeRobot
의존성이 없는 HOST 환경에서 건너뛰었다. 실제 모델 실행의 통과 근거로 세지 않는다.
로그 SHA256: `af988977d7c7d7565f4c99bddb3a637f085b7e2cc1b1a4e34aaf0210ffdbe8d0`.

앞선 136개 회귀의 runner 인자:

```text
python tools/remote/remote_pytest.py --log-dir <root>/green-total-final --
 middleware/robot_execution/local/test/test_policy_lease.py
 middleware/robot_execution/local/test/test_policy_camera.py
 middleware/robot_execution/local/test/test_policy_chain.py
 middleware/robot_execution/local/test/test_omx_policy_session.py
 middleware/robot_execution/local/test/test_policy_runtime_binding.py
```

원시 최종 로그 SHA256:
SHA256 `3beb7ef5521add3d99488d2f8c87a3e9a05f7e93f28461f55c6277dd2a6f81c3`.
독립 reviewer는 이 원시 로그의 136 passed와 hash를 확인했다. 실행 SHA·선택은
runner receipt와 위 명령을 함께 사용해야 하며, pytest의 세 줄 출력만으로 식별하지 않는다.
이후 `d7ee20bfc`는 문서와 fixture credential의 0600 생성만 추가했다.

## Gazebo 실행 결과

commit `62971299f71b97fed94681f4b749ece3dd946796`를 AI 시험 PC의 `remote_sim.py`로 실행해
`OMX_POLICY_CHAIN_GAZEBO_PASS`, teardown 뒤 `OMX_POLICY_CHAIN_EXIT_OK`, runner exit 0을 확인했다.
[수신·실행 receipt](native-receipt.json)는 외부 `chain-result.json`과 같은 JSON 값이다.
[runner 완료 기록](runner-receipt.json)은 요청한 전체 SHA·명령과 도구의 exit 0을 연결한다.
원시 `run.txt` 자체는 전체 SHA와 원격 exit code를 담지 않으므로 이 기록과 함께 사용한다.

- 첫 목표 +0.01rad: 원래 관절 위치 0.0000000181752rad에서 0.0100000146776rad로 이동했고,
  native goal `238735d4-8be7-4da7-808a-96228e26f113`의 SUCCESS를 확인했다.
- 실제 RGB 바이트와 SDK 수신 hash가 일치했고, SDK 프로세스는 ROS를 import하지 않았다.
  같은 lease의 실제 발급 시각 갱신과 SQLite 원장을 함께 확인했다.
- 두 번째 목표 이동 중 승인 창을 닫았다. 폐쇄 HTTP 응답 후 0.295306초에 해당 goal의
  cancel ACK와 CANCELED를 관측했고 owner는 HOLD였다. 마지막 0.3초의 서로 다른
  14개 관측에서 위치 spread는 0rad였다. 이는 SIM의 표본 기반 확인이며 물리 정지 인증은 아니다.
- SDK 재접속이 거부됐고 stop fence는 닫혔다. executor·worker 종료는 true, primary error는 null,
  잔여 thread stack은 없었다. 다만 종료 후 `cannot use Destroyable because destruction was requested`
  미회수 예외 경고 1건이 남아 warning-free shutdown으로 표시하지 않는다.

사전 CORE 준비 0.415948초, 실제 port가 연결된 앱 생성 0.164944초, 실제 HTTP 시작
0.095807초였다. intake 기록은 644개 중 601개 수용, 43개 거부였으며 수용 source age의
최댓값은 0.05초였다. 이전 실패의 원인을 이 한 실행으로 모두 확정하지 않는다.
특히 `1d1faf1fc2`의 정지 assertion 실패는 당시 표본 누락으로 원인이 미확정이다.

외부 근거 root는 `gazebo-chain-prepared-core/`다. SHA256:

| Artifact | SHA256 |
|---|---|
| `run.txt` | SHA256 `8c5371795b11d2d41c1c92be47d2b441a7fe1e0be0815be4fb6ea365ae484a97` |
| `chain-result.json` | SHA256 `cb2fb5e6dfb50cb5ed67b61a6fba8ca1fe54522b0b9b87abb2036194211ec92b` |
| `stop-readback.json` | SHA256 `c680e1b5343658bfac8b1b2bab62665f3a5afdc1f4aa4c04e633dc98ecf9ac79` |
| `teardown.json` | SHA256 `cc2ef9a254ba7b587cd326c0581d0523aeb2daa8b36bf2f92307a732c39c4fd1` |
| `joint-intake.json` | SHA256 `47dc88d274d2165be20f8184c076a59dbfb89249ffb5f27fdf4bd8d7d86d6887` |

### 진행 중 보존한 회귀·실패

준비된 통신 helper의 최종 원격 회귀는 `85dfae7860`에서 **222 passed in
23.32s**, runner exit 0이다. 위 선택의 7개 파일을 동일하게 실행했으며,
helper 재사용·drip 응답의 전체 deadline·진행 중 종료·잘못된 framing과
descriptor 유지 및 종료 후 응답 거부를 포함한다. 외부 로그는
`green-prepared-transport/run-1.txt`, SHA256은
SHA256 `dea1512a82a430f3f9c3242292b69d851c97b3d627fd30a049d1bf2ca543d96d`이다.

`policy_chain_gazebo.py`는 `remote_sim.py`를 통해서만 실행한다. 원본 world의
hash와 32×24 RGB/10Hz, physics step 0.002초인 명시적 시험 variant의 hash를 기록한다.
이미지 크기를 provider에서 숨겨 변환하지 않는다. 실제 LeRobot 0.4.4 별도 프로세스,
Fleet/CORE HTTP 인증, 원본 Gazebo 카메라, 기존 OMX owner와 vendor controller를 사용한다.

- `28cb02e233`, `gazebo-chain-run/run.txt`: Fleet의 World source import 누락으로
  ROS/로봇 명령 전에 중단. source 경로를 보완했다.
- `87abee0f43`, `gazebo-chain-age-run/run.txt`: 카메라·컨트롤러 준비 뒤 chain admission이
  거절됐다. 목표는 보내지 않았다. teardown에서 Destroyable 경고도 발생했다.
- `ebcb62f4d`, `gazebo-chain-admission-run/run.txt`: `admission.json`의 실제 owner는
  `hold / owner_clock_jumped_back`, observed sequence 474였다. 나머지 결속 조건은 일치했다.
- `302614ef41`: 원래 시각에서 source age를 차감한 값이 직전 수용 관측보다 역행하면
  intake에서 거부한다. timestamp를 다시 찍거나 clamp하지 않고, owner 전달·source/sequence
  commit 전에 차단한다. 기존 freshness·clock·HOLD 규칙과 recovery는 변경하지 않았다.
- `8f9a3fb97`: 기존 native fixture의 worker drain 패턴을 재사용해 ROS entity 파괴 전에
  executor와 worker 종료를 확인한다. `teardown.json`으로 실패와 잔여 thread를 보존한다.
  실제 owner ready는 확인했으나 SDK policy 요청은 403으로 거절됐다.
- `375f18c27`: 다음 실행은 lease 획득에서 fail-closed로 중단됐다. 별도 시험 준비를
  중단하며 남았던 본 세션의 예약 2개는 job 상태와 dependency build lock이 없음을
  확인한 후 해당 `.resv` 파일만 정리했다. 다른 작업·venv·서비스는 변경하지 않았다.
- `24d412a706`: SDK connect 이후 첫 observation의 403 사유는
  `policy_lease_expired_or_invalid`였다. 카메라 age 0.125초는 한도 안이었다.
  초기 HTTP 3회 합계 0.341초, 고정 대기 0.25초, 갱신 HTTP 3회 합계 0.542초로
  원래 1초 기한을 넘겼다. `exchanges.json`, `core-refusal.json`, `session-close.json`에 보존했다.
- `c7792975d0`: 현재 lease의 남은 시간에서 HTTP 최대 0.25초 × 3회 예산을 먼저
  남기고 대기한다. 격리 stdlib 프로세스에 `-S`를 추가해 불필요한 site 초기화를
  제거했다. 1초 lease·기본 HTTP timeout 0.2초·freshness와 만료 방어는 유지한다.
  두 번의 교환이 1초 안에 들어오지 않는 지속 지연에서는 여전히 HOLD가 올바르다.
  이 revision의 최종 Gazebo 통과 결과는 아직 없다.
- `80f82b11dd`: stdlib 프로세스 시작 0.0759초, 준비된 Fleet 조회 0.0297초를
  측정했다. 요청마다 새 프로세스를 시작하는 비용 때문에 갱신이 기존 lease
  기한을 넘겼다. 시험 thread 수를 제한한 실행에서도 timeout이 발생했으며,
  해당 구간의 CPU throttling count는 증가하지 않았다.
- `85dfae7860`: lease 발급 전에 명시적 POSIX context에서 stdlib helper 하나를
  준비한다. 준비 단계는 HTTP 요청을 보내지 않는다. 각 요청의 0.2초 deadline,
  전체 왕복 시간을 차감하는 1초 lease, framing 제한과 실패 시 영구 폐쇄는 유지한다.
  close는 helper를 먼저 종료하고 진행 중 I/O가 끝난 뒤 descriptor를 닫으며,
  최종 응답도 폐쇄 상태와 동기화한다. 독립 소스 리뷰의 동시성 지적 두 건을 수정했다.
  이 revision의 Gazebo 실행은 자원 기준을 충족하는 host를 기다리고 있다.
- `85dfae7860`의 실제 Gazebo에서는 초기 HTTP 3회가 0.217초로 줄었지만,
  다음 POST가 timeout으로 차단됐다. `1327001f4`의 서버 계측은 승인 요청
  0.180초 중 저장소 처리 0.006초 등 저장소 밖 대기 구간을 확인했다.
  이를 GIL만의 원인으로 확정하지 않는다. CPU throttling count 증가도 없었다.
- `b0e29b1f5c`부터 Fleet을 ROS executor와 별도 프로세스로 실행한다.
  CORE HTTP와 ROS는 기존 동일 프로세스다. 기존 실제 HTTP/auth/SQLite와
  시간·권한 검증을 그대로 사용한다. 해당 revision의 연결 단절 시험은 close
  hook 누락으로 1 failed/11 passed였으며, `435847b9bc`에서 수정 후
  **12 passed in 23.76s**, runner exit 0을 확인했다.
- 첫 별도 Fleet Gazebo 실행은 `rosy.contracts.learning` source 경로 누락으로
  lease 발급 전에 중단됐다. `1d1faf1fc2`에서 경로를 추가했다.
- `1d1faf1fc2`, `gazebo-chain-isolated-contracts/run.txt`: 실제 SDK 관절 목표의
  SUCCESS(status 4), readback 변화 >0.007rad·목표 오차 <0.003rad, 같은 lease의
  실제 갱신, 두 번째 목표 이동 중 승인 창 폐쇄, 해당 목표의 cancel ACK와
  CANCELED(status 5)·owner HOLD까지 assertion을 통과했다. HTTP 52회 중 최대
  RTT는 0.15043초였다. 그러나 정지 확인의 마지막 0.3초에서 3개 이상 관측과
  위치 spread <0.001rad를 함께 요구한 assertion이 실패했다. 원시 관측이 그
  assertion 전에 저장되지 않았으므로 샘플 부족과 계속된 움직임을 구분할 수 없다.
  전체 PASS와 재연결 거부는 확인하지 못했다. `d5cfb0ccc`는 정지 관측을 assertion
  전에 `stop-readback.json`에 보존한다. 수용 기준은 완화하지 않았다.
- `6e17064cbc`: 원본 RGB capture A 이후 새 프레임 B가 도착해 CORE의 exact-frame
  검사가 거절했다. `9478923c8`에서 capture context가 원본을 검증·복사까지 pin한다.
  watchdog의 current 읽기는 immutable snapshot을 잠금 없이 한 번 읽는다.
  lock 대기 전 수신 anchor를 보존하며 대기 후에도 원래 freshness를 검사한다.
  기존 exact-frame/hash/lease 검사는 유지했다. 독립 리뷰의 timestamp 지적을 수정했다.
- `d10eb9e4ae`: 실제 Gazebo는 첫 SDK policy 요청에서 `policy_observation_stale`로
  중단됐다. 카메라와 Fleet 갱신은 유효했다. `62971299f`는 CORE import/schema/HTTP
  준비를 lease 전에 수행하고, 최종 앱은 기존 services-bound E-stop 결선으로 생성한다.
  준비 시간과 원래 joint intake의 source/receipt·거부 이유를 제한된 trace에 남긴다.
  cold startup이 원인인지는 아직 확정하지 않는다.

probe는 합성 관리자 승인과 고정 +0.01rad 목표를 사용한다. fixture의 설치 binding은
선언한 시험 설정에서 구성하며, 외부에서 승인된 학습 release의 설치를 검증하지 않는다.
실제 학습 모델의 추론·정확도, 실제 운영자의 승인, Mission admission, 물리 로봇 이동과
물리 정지 수용은 이 검증의 범위 밖이다.

## 착지

첫 제품 착지 candidate `faa12fcdcc`의 guard는 246 passed/1 failed였다.
`test_moved_roots_leave_nothing_behind`가 fixture의 서로 다른 검색 경로 문자열
`operations/processes/palletizing/src`, `contracts/foundation`을 옛 경로 join으로
읽었다. 단독 재실행도 실패했고 같은 검사는 main `9acdf6685c`에서 통과했다.
foundation 경로를 목록 앞에 두어 문자열 인접성을 없앴다. 실제 검색 경로 집합과
fixture의 HTTP·승인·실행 검증은 유지하며, 수정된 커밋으로 검사를 다시 요청한다.

수정 commit `266c5d259`의 원격 경로 검사와 실제 Fleet HTTP 연동 검사는 13개 통과,
runner exit 0·NEW 0이었다. main 병합 candidate `04390a11de`의 guard는 247개 통과했다.
영향 범위 검사는 1631 passed/15 skipped/1 failed였고, 명시적으로 실행한 브라우저
네 묶음은 14+14+14+6개 통과했다. 실패는 이 보고서의 공개 commit·SHA256 값에
같은 줄의 무결성 표기가 빠져 비밀정보로 탐지된 것이다. 자동 단독·main 재검사는
잘못 구성된 pytest 항목 경로로 exit 4였으므로 판정 근거로 쓰지 않는다.
값을 유지하고 commit·SHA256 표기를 붙였으며 runner 기록의 키도 `source_commit`으로
명확히 했다. 검사기·예외 목록은 바꾸지 않았다. 수정 후 검사를 다시 요청한다.
독립 비교에서 SIM 통과 commit부터 candidate `04390a11de`까지 해당 제품 실행 경로와
Gazebo probe는 동일했고 fixture 검색 경로 순서만 바뀌었다. candidate 자체의 전체
SIM 재실행 결과로 표시하지 않는다.

안전 분류 prerequisite는 로컬 main commit `3c9254a52676cfcafaaa764c8eabcae5efa9692b`에 착지했다.
가장 최근 FULL candidate commit은 `4ee3f3aaa9b3445f063427a76bd70e0f68e30850`, 그 아래 main은
commit `7b11775712834f2f1dfcad68ac35e844bc12125d`였다. 외부 `safety-registration-resume/rosy-land/`
아래 22개 FULL 로그와 main 차이의 guard·affected 로그를 NEW 0으로 확인했다.
최신 main을 병합한 제품 selection은 `affected`다. 제품 착지는
`python tools/land.py --tests auto --no-prune`의 같은 candidate 검사·NEW 0과
ff-only 완료 출력으로 확인한다. 그 착지 로그와 git의 main 포함 여부가 착지 결과의 정본이다.
GitHub push와 실물 활성화는 수행하지 않았다.
