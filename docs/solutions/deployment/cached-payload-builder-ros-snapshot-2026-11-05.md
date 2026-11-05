---
title: "Changing the ROS snapshot lock does not refresh the cached payload builder"
date: "2026-11-05"
module: "Pinky native payload build and preparation"
problem_type: build_error
component: deployment
severity: high
symptoms:
  - "A successful payload build failed preparation with 211 ROS ABI mismatches."
  - "The source lock selected the new snapshot, but the workflow used an older cached builder digest."
root_cause: missing_validation
resolution_type: code_fix
tags: ["pinky", "payload", "ros-snapshot", "abi", "cached-builder"]
---

# ROS snapshot lock과 캐시된 payload builder를 함께 확인한다

## 문제와 원인

[D-482](../../adr/D-482-payload-ros-snapshot-pin.md)에 따라 source의
`inputs.lock.yaml`을 바꿔도 이미 만들어진 builder image의 설치 패키지는 바뀌지 않는다.
payload workflow는 builder를 digest로 선택하며 기본값 역시 별도다. 새 builder의 빌드가
성공해도 다음 payload가 그 digest를 사용했는지는 실제 실행 로그에서 따로 확인해야 한다.

2026-11-05 payload `2026.11.05-003`은 예전 builder를 사용했다. source lock에
새 snapshot이 있더라도 기존 준비 단계는 apt source 파일의 존재만 검사했다.
실제 artifact와 두 대상 기체에서 읽은 설치 목록을 비교하면 공유314개 중211개가 달랐다.
snapshot 날짜와 Debian 버전 안의 패키지 빌드 날짜를 같은 날짜로 해석해 고치지 않는다.
필요한 snapshot은 설치 목록과 repository package inventory를 대조해 고른다.

## 해결과 재발 방지

1. 고정 lock으로 builder를 만들고 실제 완료 로그의 digest를 선택한다. 새 payload ID를
   사용하며 기존 ID의 artifact를 고치거나 ABI 검사를 건너뛰지 않는다.
2. payload workflow는 apt 작업 전에 builder의
   `/etc/apt/sources.list.d/ros2-snapshots.sources`의 `URIs:`가
   lock의 `ros.apt_snapshot_url`과 정확히 같은지 검사한다. 다르거나 누락되면 즉시 실패한다.
3. 이 URI 검사는 image가 설정한 repository만 확인한다. 실제 설치된 패키지가 같다는
   증거는 아니다. `prepare_payload_release.py`의 artifact 대 기체 dpkg 버전 비교도 유지한다.
4. workflow 기본 builder도 검증한 digest로 바꾼다. 이 수정은 현재 작업 브랜치에서
   원격 회귀를 통과했으며 착지·게시 전이다.

## 검증 근거와 범위

- 새 builder: [run42045091165](https://github.com/robotics-team-1213/rosy-platform/actions/runs/42045091165),
  digest `62d8c7356bb4551da24b7201a5b652cef5d1bda0edbd41e08e12387f0375421f`.
- 실제 payload: [run42046327994](https://github.com/robotics-team-1213/rosy-platform/actions/runs/42046327994),
  `2026.11.05-004`, source `5adbcc36536de3bb64344b149f069c0ad1fe001b`.
  실행 로그에서 같은 새 builder digest를 사용했음을 확인했다.
- 새 artifact의 ROS inventory SHA-256은 `9f3c510c4a734e015053bc45c573a8cb9294dad49e7ad2ebc102f4adff0b492c`다.
  두 대에서 각각 읽은319개 설치 목록과 공유314개가 모두 일치했고 불일치는0개다.
  release-only28개는 공유 비교에서 제외되므로 전체 OS package 동일성으로 보고하지 않는다.
- 공식 준비 도구는 ABI 검사 후4684개 파일의 서명을 검증하고5183개 member를 포장했다.
  서명 tar SHA-256은 `7f6c2e9cd982767a71a607285cf35afc08b0c6573a25b1d77f50155e93d19073`다.
- `test/test_native_payload_workflow.py`의 회귀는 실제 workflow Python 블록을 실행한다.
  guard가 없을 때 신규3개 시험이 RED였고, 추가 후 기존 준비 도구 시험을 포함한48개가
  원격에서 통과했다. 이전 snapshot과 URI 누락은 실제 guard의 실패 경로로 검사한다.
- 실물 릴리스 활성화·부팅·지도 이동 수용은 이 준비 증거에 포함하지 않는다.

## 복구와 적용 조건

snapshot 불일치로 막히면 마지막 정상 로봇 릴리스를 유지한다. source lock과 builder가
같은지 확인하고 새 digest를 명시해 재빌드한 뒤, 두 대 각각의 실제 dpkg로 ABI를 다시
검사한다. 실제 패키지 버전이 계속 다르면 signed OS 갱신 또는 해당 OS와 맞는 builder를
준비해야 한다. 현장 패키지를 임의 upgrade하거나 버전 비교를 완화해 통과시키지 않는다.
