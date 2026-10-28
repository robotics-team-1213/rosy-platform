## D-907 Native v2 read-only signed component profile contract

**Status:** Accepted (2026-10-28)

### Context

Pinky native v1은 고정 Raspberry Pi 5/arm64/Ubuntu Server 24.04 계약이다.
OMX component를 그 manifest의 선택 필드로 확장하면 기존 형식·허용 범위와
새 설치 정책을 섞게 된다. 별도 v2와 common release owner의 읽기 전용 검증을 쓴다.
이 결정의 Accepted는 설계 수용이며 구현·설치·실물 수용을 뜻하지 않는다.

### Decision

공통 소유 위치는 `deploy/hosts/common/release/`다. 기존 Ed25519와 SHA256SUMS
구현을 재사용한다. v1 producer bytes, 검증 허용 범위·타입, Python fingerprint를 보존한다.
v2가 v1 validator나 Pinky updater에 연결되는 변경은 이 단위에 포함하지 않는다.

v2 최상위 키는 `schema_version`, `release_id`, `git_revision`, `target`, `runtime`,
`signing_key_id`, `files`, `profile`뿐이다. schema는 bool이 아닌 integer 2,
release는 `YYYY.MM.DD-NNN`, revision은 소문자 40자리 hex다. key id는 독립적으로
등록한 신뢰 public key의 stem과 같아야 한다. 모든 object는 중복·누락·추가 키와 잘못된
타입을 거부한다. object 순서만 무시한다. 배열은 정렬·유일하며 inventory는 비어 있지 않다.
파일은 정확한 `{path,sha256}` object로 선언하고 digest는 소문자 64자리 hex다.
경로는 canonical relative POSIX이며 절대·backslash·빈 segment·dot·parent alias를 거부한다.
서명 검증이 먼저이며 inventory·실제 bytes·signed checksum의 불일치를 거부한다.

`target`의 정확한 키는 `board`, `architecture`, `os_family`, `os_release`다.
`runtime`은 `model`, `python_version`, `ros_distro`다. `profile`은 `id`,
`component_role`, `entrypoint`, `unit_files`, `dependency_lock`이며 lock은
`path`, `sha256`다. 설치 caller는 target/runtime/static profile-role-entrypoint-template-lock-path
정책을 candidate와 독립적으로 제공해야 한다. candidate로 expected 값을 만들지 않는다.
lock digest는 release별 서명 데이터와 inventory/bytes에 결속한다. 설치 정책이 특정 digest를
더 엄격히 제한하는 것은 허용하되, 매 release lock의 사람 사전승인을 기본 요건으로 만들지 않는다.

첫 검토 대상 profile은 `omx-manual-device-trial.v1` / `omx-manual-owner`,
entrypoint `deploy/robot/omx/run_hardware_owner.py`, template
`deploy/robot/omx/rosy-omx-owner@.service`, lock
`deploy/robot/omx/requirements-manual.lock`다. 이 경로 이름은 실제 manual consumer,
dependency closure, Action/stop/watchdog 수용을 증명하지 않는다. NoGoalDriver를 실행 가능한
manual owner로 포장하지 않는다. Observation은 별도 profile과 검토가 필요하다.

필수 inventory는 `install/.rosy-release`, `source-revision.txt`,
`python-runtime.sha256`, `runtime-identity.json`, `runtime-system-packages.lock`,
`runtime-ros-packages.lock`, profile entrypoint/template/lock 및 실제 imports/resources다.
marker/revision은 manifest와 같아야 한다. v2 fingerprint는 runtime identity의 canonical
UTF-8 JSON(sorted keys, compact separators, newline 없음)의 SHA256이다.
identity의 정확한 키는 `os_id`, `os_version`, `architecture`, `python_version`,
`python_executable_sha256`, `python_cache_tag`, `python_soabi`, `ros_distro`,
`system_packages_sha256`, `ros_packages_sha256`, `dependency_lock_sha256`,
`system_site_packages`다. 마지막은 bool이고 나머지는 string, digest는 소문자 64자리 hex다.
두 package lock의 정확한 bytes hash와 dependency lock hash를 대조한다.
설치 caller는 실제 interpreter/OS/ROS/native closure를 별도로 관측·재계산해 제공해야 한다.
읽기 전용 parser 통과만으로 그 관측이나 native dependency 검증을 수행했다고 말하지 않는다.
검증 불가능한 closure는 후속 설치 caller가 거부해야 한다.

실제 관측 tuple Ubuntu 26.04/x86_64/Python 3.14.4와 inherited ROS_DISTRO=lyrical은
첫 amd64 closure 조사 입력이다. ROS 패키지 설치·빌드 지원이나 accepted artifact 증거가 아니다.
arm64 및 다른 tuple도 별도 closure·정적 정책·빌드·설치 증거가 필요하다.

후속 updater는 보호된 완전 identity(`release_id`, `git_revision`, `manifest_sha256`,
`env_fingerprint`, `template_sha256`)의 accepted-forward frontier를 유지해야 한다.
정상 전진의 strict Git descent, exact retry, 이전 signed identity만의 rollback,
frontier를 되돌리지 않는 복구, durable fence·quiesce ACK·session lock 재획득,
shared-template 전체 instance 조정은 이 parser가 강제하지 않는다. 그 구현·시험은 별도 단위다.
기존 activation/recovery가 이 새 계약을 만족한다고 주장하지 않는다.

| 기존 결정 | 관계 |
|---|---|
| D-427 | common release 소유 위치를 유지하며 새 최상위 구조를 만들지 않는다 |
| D-429 | 논리 profile과 실제 package/host closure를 구분한다 |
| D-430 | 명령·안전 writer를 추가하지 않으며 후속 안전 경로 변경은 독립 검토한다 |

### Consequences

첫 구현 단위는 readonly signature/shape/inventory/policy 검증과 v1 호환 회귀다.
builder/workflow/설치 profile/updater/consumer/ACK/UI·HTTP·serial writer는 후속이다.
toy fixture와 임시 키의 시험은 metadata 계약 증거이며 ARTIFACT·DEVICE·FIELD gate를 옮기지 않는다.
신규 guard는 GREEN 뒤 실제 source mutant의 원격 RED와 복원 GREEN을 확인해야 한다.
