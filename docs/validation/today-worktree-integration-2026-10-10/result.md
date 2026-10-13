# 오늘 워크트리 통합 검증

날짜: 2026-10-10. 작업 브랜치: `fix/today-worktree-integration`.
기준 main commit: `9f6a76e294b0e010575ce77375df889bc6ade2d8`.
사용자 승인 범위는 커밋과 로컬 main 착지이며, 원격 push는 포함하지 않는다.

## 독립 소스 검토

`snapshot-review /root/snapshot_review`가 수집한 브랜치 및 미커밋 스냅샷과 통합 수정을 읽기 전용으로 검토했다.
출발 장소·차체 검사를 자동 회전보다 먼저 수행하고, 모델 fallback의 floor gate를 유지했다.
같은 drivable 관측을 여러 프레임으로 세지 않으며, 경로 이탈과 source pose 소실은 보유 가설을 무효화한다.
Rosy Cam lease는 지도·교정 revision에 묶인 단일 helper를 사용한다.
AI deadlock 응답 대기와 동일 제안 재실행은 제한되고 기존 3회 한도를 따른다.

`c9ef8c34b` 검토: 순수 target 계산 세 함수는 이동 전후 AST가 같고 상수·호출 경로가 유지된다.
drivable steering 554줄, target 57줄, 단위 909줄로 810+150 이내다.
엄격한 동료 map pose 검사는 그대로 두고 시험 fixture에 지도 좌표를 보충했다.
Fleet·CLI의 기존 분리 의무와 face의 증가 허용 0을 보존한다. CLI connection/session parser 분리는 미완료다.
D-616 연속 시험 도구는 기존 heartbeat·hold lease·종료 cleanup을 유지하며 자동 재무장하지 않는다.

## 과거 검토 표시 보완

같은 독립 검토자가 아래 exact commit diff를 재검토하고 `safety_review.py`의 retrospective EXEMPT 등록을 승인했다.

- commit `8ff5c68d36c83fe9c6916a992a567420f013a949`: 안전 manager의 docstring만 변경한다. 실행 로직은 같고 D-602 person 클래스 계약 및 person_feet 거절 회귀가 일치한다.
- commit `1168199f168a9eec93747b45ee91c91670da9d1c`: 알려진 pinky_pro만 기존 공칭 차체를 선택하며 알 수 없는 기종은 None이다. 자세 관측 시각과 누적 age가 만료·잘못된 근거를 거절한다. 기존 followup 스냅샷 검토를 exact diff로 재확인했다.

이는 독립 정적 소스 승인이다. 실물 장치 수용을 뜻하지 않는다.

## 원격 시험 증거

제품 통합 candidate commit `59135857e2e98faf04d26e4c55db161e1447b571`:
AI PC와 모델 PC의 네 affected 시험 묶음에서 16,599 passed, 1,029 skipped, NEW 0.
Node 시험은 277 passed, 실패 0. lint는 오류 0이며 오래된 검증 기록 경고가 있다.
최종 추가분은 도구와 검토 기록이다. candidate `7470505e01`의 도구·루트 시험은 5,311 passed, 756 skipped와 확인 소유 목록 누락 1건을 보고했다.
호스트 서비스의 기존 공용 확인 호출을 목록에 기록하고, 안전 이력 표시는 위 독립 승인으로 보완한다. 이 보완의 원격 재검증과 착지 관문은 별도로 수행한다.

로그와 원본 스냅샷은 `X:/DevTemp/projects/rosy-platform/2026-10-10--170936--today-worktree-land--a864f6/`에 있다.
동료 워크트리와 공유 main의 미추적 파일은 보존한다. 전체 CI, ARM64 이미지, 장치·현장 수용은 이 작업으로 확인하지 않는다.

## 이어서 통합한 후속 작업

사용자의 이어서 진행 요청으로 `ec0f662272`, `a7d988244`, `1a91278f3`, `ad8f9c861`을 추가 통합했다.
`snapshot-review /root/snapshot_review`가 각 tip과 최종 `b7343fcf6`을 독립 정적 검토했다.
구형 크기 판정과 이동 전 helper를 복원하지 않고 현재 관측 중복 방지·자세 누락 시 폐기를 보존한다.
거절된 측면 출구의 latch를 지우며 앞벽의 가짜 모서리 판정만 좁힌다. 속도와 CORE 정지 권한은 바뀌지 않는다.
명시적인 지도 localization 신뢰는 현재 `stuck/peer_pose.py` 소유 경로에 반영했다.
이 단계의 독립 측정은 조향 파일 562줄, drivable 단위 917줄이다. 기존 분리 기준과 한도 안이다.

같은 독립 검토자가 다음 과거 exact commit도 재검토해 retrospective EXEMPT 등록을 승인했다.

- `ee6329045`: 명시적 LOCALIZED map만 신뢰하며, localization 누락을 시간 경과로 신뢰하지 않는다.
- `83b6b4b44`: goal 직전 현재 localization을 읽고 client identity를 재확인한다.

이는 정적 소스 승인이다. 후속 원격 시험, 안전 이력 검사와 착지 관문 결과는 별도 증거다.

## 추가 속도 설정과 포화 회귀

완료 tip `0c37fb18e`의 Pinky 0.10 m/s 순항과 gain 2.0 설정을 통합했다.
독립 검토에서 각속도 선행 clip이 D-344 곡률 유지 계약을 깨는 경우를 발견했다.
최종 cap 단계가 원래 요청 각속도와 선속도를 함께 줄이도록 선행 clip을 제거했다.
회귀 시험은 양쪽 큰 오차와 설정 상한·수동 상한·수동 상한 무시 설정을 검사한다.
원격 red 시험은 수정 전 여섯 경우 모두 실패했다. 최종 시험과 착지는 별도 관문이다.

연속 통합 candidate `b7343fcf6`의 원격 시험은 8,034 passed, 324 skipped였다.
NEW 1은 보고서 Git 해시의 비밀값 오인으로, 명시적인 git commit 표기로 수정했다.
Fleet Node 시험은 후속 통합 소스에서 272 passed, 실패 0이었다.
속도 설정의 장치 배포나 실물 제동·회전 수용을 이 기록으로 주장하지 않는다.

독립 검토자 `snapshot-review /root/snapshot_review`는 위 곡률 수정과 회귀를 정적 승인했다.
과거 `d5db5db69`의 retrospective EXEMPT도 이 수정이 같은 통합 이력에 포함되는 조건으로 승인했다.
수정 없는 과거 단독 상태는 승인하지 않았다.
