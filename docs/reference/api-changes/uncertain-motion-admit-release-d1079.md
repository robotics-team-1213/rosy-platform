---
surface: fleet
kind: additive
slug: uncertain-motion-admit-release-d1079
date: 2026-11-27
title: 불확실 이동 해제의 수락 기한 경계 (D-1079)
---
D-1079: 새 Fleet 경로·응답 필드는 없다. 기존 CORE capabilities에서 `navigation.admit_deadline`과 `navigation.generation_fence`가 둘 다 true인 경우 `/api/v1/navigation/state`의 `owner.boot_id`·`owner.owner_generation`에 capability를 묶고, navigation 시작 요청 본문에 `expected_boot_id`·`expected_owner_generation`이 둘 다 실릴 때만 `admit_within_s=3.0`을 붙인다(세대 갱신이 실패하거나 둘 중 하나라도 없으면 unbounded로 전송). 해당 요청에는 총 transport timeout(기본 5초, `asyncio.wait_for`)을 적용하며, 라우트 진입 전 지연된 요청은 해제 전에 확정하는 세대 fence가 막는다.

불확실 이동 표시는 실제 보낸 payload의 `admit_within_s`·`expected_boot_id`·`expected_owner_generation`만 기록하며, 기존 표시 이후 측정 정지 증거와 race 검사를 유지하고, 증거 조회 시작이 전송 시작 + transport timeout + 전송한 admit_within_s + 0.5초(`MOTION_RELEASE_MARGIN_S=0.5`, 실물 측정 필요) 이상일 때 정지 증거를 읽기 **전에** 참고용 사전 조회(`/api/v1/navigation/state`)로 CORE `boot_id`가 표지의 `boot_id`와 같은지 확인하고 `navigation`이 비활성(`IDLE`/`ARRIVED`/`CANCELED`/`FAILED`)일 때만 `POST /api/v1/navigation/cancel`(`{"advance_generation": true}`)을 보내 그 응답의 `owner.owner_generation`으로 세대 전진을 먼저 확정한 뒤, 그 fence 확정 시각 이후의 정지 표본과 동일한 `fenced_generation`이 확인될 때만 해제한다(기본 8.5초). 사전 조회에서 `navigation`이 활성이면 cancel을 보내지 않고 표시를 유지하며, cancel 응답에 `owner`가 없거나 `boot_id`가 바뀌었으면 해제하지 않는다(`boot_id`가 바뀌었으면 capability도 지운다). 시간만 지나거나 cancel ACK 또는 단순 `gen > expected`만으로 해제하지 않는다. 기한 없는 CORE·재부팅/롤백된 옛 CORE·협상 전·세대 갱신 실패·기한 미지원 이동은 표시를 유지하며 기존 로그에 `기한 없는 CORE라 해제 불가`를 남긴다. 배포 전에도 보수적 보류를 유지한다. 래치·custody 해제나 작업 재출발을 뜻하지 않는다.
