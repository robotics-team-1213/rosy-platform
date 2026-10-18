# OMX SIM Fleet → CORE → LeRobot → Gazebo integration

2026-10-19. 사용자는 학습 checkpoint가 없으며 고정 SIM 정책으로 전체 경로부터
검증하도록 선택했다. 실물 배포 대상과 승인된 정책 revision도 없다.

## 구현과 권한

기존 Fleet의 인증된 policy state/lease HTTP를 장치 consumer가 읽고, 기존 CORE
arm port와 dedicated steady-clock OMX owner에 결속한다. SDK는 관측·목표·정지만
요청한다. 설치 pin, local AttemptIdentity, window, rig, calibration, episode와
owner session은 SDK 입력에서 받지 않는다. ROS callback은 검증된 local cache만 읽는다.

기본값은 비활성이며 SIM 설치만 허용한다. 최대 1초 lease에서 요청·readback 시간을
차감한다. 각 HTTP 교환은 소유한 격리 subprocess에서 0.2초 timeout으로 실행하고,
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

최종 GREEN의 runner 인자:

```text
python tools/remote/remote_pytest.py --log-dir <root>/green-total-final --
 middleware/robot_execution/local/test/test_policy_lease.py
 middleware/robot_execution/local/test/test_policy_camera.py
 middleware/robot_execution/local/test/test_policy_chain.py
 middleware/robot_execution/local/test/test_omx_policy_session.py
 middleware/robot_execution/local/test/test_policy_runtime_binding.py
```

원시 최종 로그 SHA256:
`3beb7ef5521add3d99488d2f8c87a3e9a05f7e93f28461f55c6277dd2a6f81c3`.
독립 reviewer는 이 원시 로그의 136 passed와 hash를 확인했다. 실행 SHA·선택은
runner receipt와 위 명령을 함께 사용해야 하며, pytest의 세 줄 출력만으로 식별하지 않는다.
이후 `d7ee20bfc`는 문서와 fixture credential의 0600 생성만 추가했다.

## Gazebo 실행 상태

준비된 통신 helper의 최종 원격 회귀는 `85dfae7860`에서 **222 passed in
23.32s**, runner exit 0이다. 위 선택의 7개 파일을 동일하게 실행했으며,
helper 재사용·drip 응답의 전체 deadline·진행 중 종료·잘못된 framing과
descriptor 유지 및 종료 후 응답 거부를 포함한다. 외부 로그는
`green-prepared-transport/run-1.txt`, SHA256은
`dea1512a82a430f3f9c3242292b69d851c97b3d627fd30a049d1bf2ca543d96d`이다.

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

probe는 합성 관리자 승인과 고정 +0.01rad 목표를 사용한다. fixture의 설치 binding은
선언한 시험 설정에서 구성하며, 외부에서 승인된 학습 release의 설치를 검증하지 않는다.
실제 학습 모델의 추론·정확도, 실제 운영자의 승인, Mission admission, 물리 로봇 이동과
물리 정지 수용은 이 검증의 범위 밖이다.

## 착지

안전 분류 prerequisite는 별도 FULL 검사 중이다. 제품 branch의 최종 affected 검사와
로컬 main 착지는 아직 완료하지 않았다. GitHub push와 실물 활성화는 수행하지 않았다.
