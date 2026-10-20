# 설치 충전 계측 source 계약

[D-776](../adr/D-776-installed-station-charge-facts.md)의 로컬 사실 포트는 `fleet.server.charge_source.ChargeFactSource`다. 현재 이 포트와 replay/시간 검증은 구현됐으며 운영 CLI·실제 경로 비용 조립은 후속 단계다. 파일 작성 BMS/게이지 어댑터나 실제 장치의 지원·정확도를 증명하지 않는다.

## 작성 주체와 파일

설치자가 승인한 POSIX writer UID가 원본 motion과 배터리 계측을 수집한다. 원본 자료에 UTC capture·expiry, boot/odom 세대와 신뢰 가능한 장치 출처가 없으면 유효한 측정으로 발행하지 않는다. 호스트 수신 시각으로 오래된 자료를 다시 찍거나 voltage-only 자료를 SOH/실측 용량으로 바꾸지 않는다.

writer가 소유하고 group/other 쓰기가 없는 디렉터리를 사용한다. 같은 디렉터리에 완성한 일반 파일을 쓴 뒤 원자적으로 rename한다. 파일도 같은 UID 소유이고 group/other 쓰기가 없어야 한다. reader는 symlink/hardlink·다른 UID·공유 쓰기 디렉터리·비일반 파일·64 KiB 초과·read 중 제자리 변경·깨진 UTF-8/JSON·중복 키·NaN/Inf를 거절한다. 이 전송은 POSIX descriptor 검증을 요구하며 Windows ACL 추정으로 대체하지 않는다. 비밀·명령·경로 예산·선택 작업·미래 session은 파일에 넣지 않는다.

`ChargeFactProfile`에는 robot/battery/source ID, 승인 source epoch, map ID/revision, writer UID, 최대 계측 나이, 정지 dwell와 선속도/각속도 한계를 명시한다. 프로필 값은 설치 승인 입력이며 실기 교정 수용의 자동 증거가 아니다. source epoch를 자동 재연결이나 sequence 초기화로 변경하지 않는다.

## 발행 자료

다음은 만료된 형식 예제다. 실제 장치 설정이나 측정값이 아니며 배터리 근거는 의도적으로 미제공이다.

```json
{
  "robot_id": "example-robot",
  "battery_id": "example-pack",
  "boot_id": "example-core-boot",
  "source_id": "example-measurements",
  "source_epoch": "example-source-epoch",
  "sequence": 1,
  "map_id": "example-floor",
  "map_revision": "example-map-revision",
  "odom_epoch": "example-odom-epoch",
  "mode": "IDLE",
  "safety_latched": false,
  "dock_state": "UNDOCKED",
  "measured_linear_m_s": 0.0,
  "measured_angular_rad_s": 0.0,
  "still_since": null,
  "captured_at": 0.0,
  "valid_until": 1.0,
  "battery_energy": {
    "battery_id": "example-pack",
    "source": "unknown",
    "capacity_revision": null,
    "soc_percent": null,
    "soh_percent": null,
    "usable_energy_wh": null,
    "temperature_c": null,
    "fault": "MEASUREMENT_MISSING",
    "captured_at": 0.0,
    "valid_until": 1.0
  }
}
```

최상위 capture는 원본 motion sample 시각이다. battery capture와 still_since는 이를 넘지 않는다. still_since는 승인된 계측 owner가 연속 정지를 검증한 시작 시각이며 모르면 null이다. reader는 모드·안전 래치·원본 정지 dwell·측정 속도에서 safe_work_boundary만 계산한다. CORE의 실제 native owner·정지·접점·충전 종단 확인을 대체하지 않는다. 배터리는 기존 BatteryEnergyEvidence 계약을 따른다.

## 수명·재시작·오류

사용 전에 기존 TaskStore SQLite에 source별 sequence·canonical payload hash·원본 motion/battery capture/hash와 replay 거절 watermark를 저장한다. path나 최대 나이 변경으로 이를 초기화하지 않는다. 같은 sequence는 같은 자료여야 하고 새 sequence는 원본 motion capture도 증가해야 한다. 같은 battery capture의 값·expiry를 바꿀 수 없다.

같은 프로세스에서 반복 읽기는 최초 monotonic 만료를 유지한다. 새 motion envelope도 그대로인 battery 자료의 최초 만료를 연장하지 않는다. 반환 snapshot의 expiry는 원본 UTC/최대 나이와 남은 monotonic 수명의 더 짧은 값이다. 시계 읽기·파일 I/O에 걸린 시간을 유효기간에 추가하지 않는다. UTC/monotonic 역행이나 관측된 실패 뒤 이전 자료 복원은 거절한다.

새 reader/process는 보존 watermark보다 새로운 sequence와 원본 motion/battery capture를 요구한다. 실패한 읽기는 마지막 수락 자료를 폐기하며, 거절된 입력의 임의로 큰 sequence를 승인 watermark로 사용하지 않는다. DB 오류나 저장 실패에서는 자료를 반환하지 않는다. 호출 오류는 `CHARGE_SOURCE_UNAVAILABLE`이고 blocking 파일/DB 처리는 async 루프 밖에서 한다.

후속 Fleet 조립은 실제 World 자세·활성 그래프·선택 Task·승인 비용 모델에서 예산을 계산하고 기존 정책 및 CORE 명령 경계를 사용한다. 이 포트 자체에는 이동·접안·충전·이탈 명령 권한이 없다.

## 기존 World 입력의 선택적 출처 결속

`MapPoseService.begin_source_scope(robot_id, boot_id=..., odom_epoch=..., client=...)`는 신뢰된 내부 조립자가 native identity를 확인한 뒤 사용할 로컬 선언 포트다. 이 호출이나 반환 ticket 자체는 boot 검증 증거가 아니다. 최초 선언과 boot/CORE epoch/client/map ID 변경은 기존 World tracker와 cached state를 폐기한다. 별도 위치 계산기는 만들지 않는다.

이후 해당 로봇의 일반 hub/REST sink 입력은 qualified tracker나 cache를 채우지 못한다. 선언 전에 시작한 읽기도 시작 generation을 비교해 늦은 완료를 버린다. `observe_qualified_state(ticket, state)`는 robot/map/정수 CORE epoch와 경계 이후의 원본 CORE odom stamp를 검사해 기존 tracker에 공급한다. 경계 전 카메라 capture와 old ticket은 거절한다. 잘못된 원본 자료 뒤 같은 마지막 sample을 재생해 proof를 복원할 수 없다.

`qualified_pose(ticket)`는 같은 원본 odom과 새 camera anchor를 사용하는 기존 World의 LOCALIZED 자세만 읽는다. operator pin은 이 camera proof를 대신하지 않는다. World accessor 이후에도 ticket·clock·원본 odom/anchor age를 확인하며, 이 경계의 시간 정책은 기존 World UTC age다. epoch와 tracker 내부 reset counter를 같은 값으로 취급하지 않는다.

이 선언 포트의 native 검증은 아래 reader가 담당한다. 운영 charging factory와 예산의 원본 timestamp 결속·실행 비용 상한은 후속 조립 대상이다. 선언만으로 native 확인을 완료했다고 기록하거나 이동을 승인할 수 없다.

## Native 부팅 응답과 공유 상태의 대조

`ChargeWorldPoseSource.read(facts)`는 기존 client의 `docking_status()` 부팅 응답 → 새 공유 REST 상태 → 부팅 응답 순서로 읽는다. `StateSourceRead`는 공유 reader가 캡처한 client 자체로 요청하고, 다른 sink가 원본 응답을 수정하기 전에 불변 JSON 사본과 client/generation/read number/요청 시작 monotonic 시각을 보존한다. `state_with_source()`와 일반 `state()`는 같은 요청과 cache를 공유한다. 전송 receipt 저장과 World 입력 수락은 별개이므로, bound 상태에서도 공유 주기를 유지하되 검증되지 않은 입력은 tracker를 채우지 못한다.

두 boot 응답·실제 sender·CORE 정수 epoch·원본 facts/map revision·시간이 일치한 뒤 기존 World에 입력한다. 최초 fresh odom이 선언 경계 이전이면 새 odom을, LOCALIZED camera anchor가 없으면 새 카메라 관측을 기다리며 `None`을 반환한다. 정상 대기에서 cutoff를 반복 초기화하지 않는다. 실제 모순·오류는 scope와 발급 proof를 폐기한다. 최종 `current(proof, facts)`도 관측한 모순을 보류하고 원래 client/map을 복구해 같은 proof를 되살리지 않는다.

facts·odom·camera anchor는 각각 최초 monotonic deadline을 보존한다. 새 motion이 같은 anchor나 같은 facts의 수명을 늘리지 않는다. 이 reader의 facts capture 역행과 같은 capture의 immutable scope 변경을 거절하고, exported TTL 변경으로 최초 수명을 연장하지 않는다. 새 reader는 기존 scope를 한 번 폐기하고 새 원본 자료를 요구한다.

이 내부 reader는 실행 명령이나 유한 경로 비용을 승인하지 않는다. 상위 facts는 승인된 ChargeFactSource에서 받아야 하며, 이후 예산은 발급된 불변 proof와 원본 facts·최종 `current()` 확인에 결속해야 한다. 현재 운영 charging factory에는 아직 연결하지 않았다. Fake client 기반 원격 회귀와 현장 CORE 부팅 대조 수용은 별도 근거다.
