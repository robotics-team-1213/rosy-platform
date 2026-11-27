## 2026-11-27 · uncommitted · D-1079 navigation 수락 직전 단조 기한 검사

- 변경: goal/home/route 공통 admission 락에서 deadline 초과 거절 및 cancel(advance_generation=True) 무동작 세대 fence 추가; 수신 시각은 API 본문·의존성·threadpool 대기 전 보관; 여섯 시작 경로 전체의 localization·nav 락 대기 및 옛 세대 OWNER_GENERATION_CHANGED 거절 시험 포함
- 증거: 원격 시험(모델 PC·AI PC) CORE 630 passed, Fleet 546 passed, known_failures 0 new(b053a0413d), 독립 D-430 검토 4회차 APPROVE·5회차(변경분 e496ca632d..b053a0413d) APPROVE; docs/validation/fleet-uncertain-motion-2026-11-27/result.md D-1079 절 참조
- gate 변화: 없음
- 결정: D-1079 Proposed; 실제 구현 core_features.navigation, 최종 writer와 프로세스 구조 유지
- 교훈: 없음
