## D-367 Rosy Pilot 의 체감 응답속도는 카메라 폴링 150ms·명령 루프 100ms·햅틱 10ms 로 잡는다

**Status:** Accepted (2026-09-29, 응답속도 설계). 실측 근거: dev_server 5ms 평균 teleop 지연.

## Context

Pilot 주행 화면의 체감 지연은 세 층이 겹친다: (1) 카메라 프레임 폴링 주기, (2) hold-to-drive
명령 루프 주기 + 네트워크 지연, (3) 조종 입력의 시각·촉각 피드백 지연. NFS 계열 모바일
게임의 체감 기준은 조향 반응 <50ms, 영상 갱신 <200ms, 페달 피드백 즉각(0ms)이다.
측정 결과 teleop POST 평균 5ms(dev_server 기준)로 네트워크는 병목이 아니며, 남은
병목은 폴링 주기와 피드백 타이밍이다.

## Decision

1. **카메라 폴링 150ms**: vision.js 의 폴링 주기를 200ms → 150ms로 내린다. 시퀀스가
   같으면 프레임을 유지하므로(숨기지 않음) 150ms는 체감 부드러움만 올리고 부하지는
   33% 늘린다(6.7Hz → 실측 5Hz 소스).
2. **명령 루프 100ms 유지**: hold-to-drive 루프는 100ms 그대로. CORE 의 SAF-002
   watchdog 이 명령 소실을 잡으므로 더 빠르게 보낼 필요가 없다(과도한 POST 는
   Command Manager 에 부하만 추가).
3. **페달 햅틱 10ms**: `navigator.vibrate(10)` 를 pointerdown 시 즉시 호출한다.
   시각 피드백(active 클래스)보다 촉각이 먼저 도달해 체감 반응을 0ms 로 만든다.
4. **휠 인디케이터 30ms**: 조향 회전 표시의 CSS transition 을 60ms → 30ms 로 내려
   드래그 추격감을 높인다.
5. **카메라 프레임 페이드**: img 에 `opacity 150ms ease-out` 전환을 걸어 프레임
   교체 시 깜빡임을 없앤다.

## Consequences and rollout

체감 지연이 눈에 띄게 줄어든다(카메라 150ms + 명령 105ms + 햅틱 즉각). 폴링 빈도
증가는 CORE vision store 에 무의미한 부하를 주지 않는다 — 시퀀스가 같으면 fetch 를
건너뛴다. 실기 CORE(Pi 5)에서 네트워크 지연이 50ms+ 로 늘어나면 루프 주기를 별도
조정한다(후속 게이트).

**Related:** [D-323](D-323-rosy-pilot-teleop-app.md), [D-365](D-365-pilot-pwa-first.md).

---
