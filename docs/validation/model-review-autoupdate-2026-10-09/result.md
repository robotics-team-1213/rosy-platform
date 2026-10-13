# 모델 PC 검수 UI와 관제 PC 자동 업데이트 확인

2026-10-09 현장 readback. 장비 주소·계정·비밀은 기록하지 않는다.

| 대상 | 확인한 상태 | 경계 |
| --- | --- | --- |
| 모델 PC D-446 | `rosy-model-code-update.timer` enabled/active, sequence 19의 승인 코드 커밋과 현재 링크 일치. 최근 주기는 `idle` | 새 승인 후보의 전환 시험은 별도 |
| 모델 PC 검수 UI | `uiux-d8f1232-20261009` 릴리스 설치, `rosy-review-v13.service` active, `/api/workspace`·`/pixels` 200 | 브라우저의 승인 저장과 학습 반영은 별도 |
| 모델 PC D-561 | `rosy-review-release-update.timer` enabled/active. 기준 sequence 19에서 `waiting for a newer accepted model-code release`로 기존 화면 유지 | sequence 20 이상의 실제 서명 후보 적용 후 자동 전환은 아직 미검증 |
| 관제 PC D-441 | `rosy-site-autoupdate.timer` enabled/active. 서명된 `site-82a9ac61e618` 설치 기록, 최근 주기 `idle`; proxy·Fleet·Vision 이미지 태그 일치 | 설치된 사이트 UI의 모든 기능 검증은 별도 |
| 관제 PC 옛 타이머 | `rosy-site-update.timer`도 enabled/active | D-530의 중복 제거는 관리자 sudo가 필요해 미완료 |

모델 PC 자동 갱신의 로컬 호스트 테스트는 Windows에서 1 passed, 3 skipped (`known_failures.py` NEW 0), 모델 PC Linux에서 2 passed다. 모델 PC 사용자 서비스의 실제 첫 실행은 기준 sequence에서 기존 화면을 보존했다. 공유 `main` 착지 검사는 다른 세션이 선점했지만 아직 본문이 없는 D-558–D-560 때문에 lint가 실패했다. 번호를 임의로 gap 처리하지 않는다.
