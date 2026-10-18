## D-746 SD 카드의 기존 robot identity를 덮어쓰지 않고, 재이미징은 배포 설정을 유지한다

**Status:** Proposed
**Date:** 2026-10-13

## Context

`prepare-rosy-sd.ps1`은 카드 전체를 지운다. 카드에 이미 다른 robot의 `rosy-provision/provision.json`이 있어도 계획과 쓰기가 막지 않았고, 계획 때 본 카드와 쓰기 때 꽂힌 카드가 같은 디스크 서명이면 통과했다. 같은 robot을 새 release로 다시 쓰는 `-ReprovisionReceipt`는 identity만 받고 Model, Preset, CountryCode, Fleet 값은 매번 기본값으로 돌아갔다. 폐기된 `feat/sd-identity-mode`가 같은 문제를 다뤘고 그 브랜치의 번호 D-324는 main에 없다.

## Decision

1. 카드에 `provision.json`이 있으면 `device_name`과 `device_uid`를 읽는다. 영수증 없이 새 identity를 쓰려면 `-ReplaceExistingProvision`이 있어야 하며 없으면 두 robot 이름을 대며 거절한다. 비밀값은 출력하지 않는다.
2. `-ReprovisionReceipt`(재이미징)는 카드의 identity가 영수증과 같을 때만 쓴다. 다르면 거절하고 `-ReplaceExistingProvision`과 같이 쓸 수 없다.
3. 재이미징은 영수증의 Model, Preset, CountryCode, Fleet endpoint·trust를 명시하지 않은 값에 이어 쓰고, 검토한 plan이 그 값을 고정한다. 이전 카드에 operator SSH 키가 있었으면 `-OperatorPublicKey`를 다시 요구한다.
4. plan과 receipt에 `replace_existing_provision`, `prior_device_name`을 남기고, plan에는 `prior_provision_sha256`도 남겨 검토 뒤 카드가 바뀌면 쓰기를 거절한다. `-ResumeAfterWrite`는 이미 덮어쓴 카드라 이 검사를 건너뛴다.

## Consequences

잘못 꽂은 카드는 지우기 전에 멈춘다. 의도한 교체는 plan 단계에서 한 번 명시한다. SSID와 Wi-Fi 비밀번호는 영수증에 없어 재이미징에서도 profile로 다시 준다. 실제 카드 쓰기와 장치 부팅은 이 결정에서 확인하지 않았다.
