## D-552 램프·화면·소리는 한 레코드(`Presentation`)에서 나오고, 화면은 위쪽 상태 바와 아래쪽 표정 영역으로 나뉜다

**Status:** Proposed (2026-10-09, 사용자 요청: "LED와 화면이 한 규칙으로 같이 움직여 일관돼야 한다. 화면에 이모티콘(표정)을 보여 주는데, 표정과 로봇 상태와 배터리를 더 잘 보여 주자. 화면을 표정 영역과 상태 바로 나누자"). 구현은 이 브랜치(`uiux/face-presentation-panes`)가 한다. 실기(램프·화면 동시 변화, 가독 거리)는 DEVICE 수용이 따로다. 표시·소리 경로(`rosy-face`)는 Safety-Review 대상일 수 있다.

**부분 개정(수락 뒤 적용):** [D-433](D-433-one-face-process-owns-lcd-buzzer-lamp.md) 결정 2의 9–11행(얼굴 밑 띠)과 [D-546](D-546-recovery-manoeuvre-signals-and-fleet-pose-request.md) 결정 2의 우선순위 한 줄을 아래 "개정 목록"대로 고친다. 그 전에는 두 ADR이 그대로 이긴다.

잇는 결정: [D-260](D-260-robot-shows-its-state-by-sound-light-screen-and-summary.md)(한 상태·소리·램프) · [D-380](D-380-lamp-mode-patterns-from-core-status-inputs.md)/[D-381](D-381-blocked-navigation-and-emergency-entry-sound.md)(램프 모드 패턴·우선순위) · [D-385](D-385-rosy-expresses-itself-mode-faces-and-breathing-boot.md)(모드 얼굴) · [D-433](D-433-one-face-process-owns-lcd-buzzer-lamp.md)(`rosy-face`가 LCD·부저·램프의 유일한 소유자) · [D-472](D-472-rosy-cam-map-and-lamp-identity.md)(식별) · [D-483](D-483-robot-screen-approval-code-for-peer-requests.md)(승인 코드 카드) · [D-546](D-546-recovery-manoeuvre-signals-and-fleet-pose-request.md)(복구 신호).

### Context

코드에서 읽은 사실이다(2026-10-09 main).

- 램프는 `robot_state.lamp_pattern(state, mode, nav_state, recovery)`가, 화면은 `face_screen.screen_for`가 같은 입력을 따로 읽어 정한다. 모드는 램프가 10 s 지연되는 `boot-status.json`에서, 화면이 1 s `face-inputs.json`에서 읽는다.
- 그래서 둘이 어긋나는 입력이 있다. (1) `estop`이 걸렸는데 모드가 EMERGENCY가 아니면 화면은 STOPPED 카드인데 램프는 주행 무늬다. (2) CORE 주의 코드(`line_follow_hold`·`dock_failed`)는 주황 띠만 그리고 램프와 소리는 평소다. (3) `bridge` 복구 중에 배터리가 낮으면 램프는 `bridging`(호흡)인데 화면은 주황 "Charge the battery"다. (4) CORE가 고른 얼굴이 `happy`인데 램프는 주황 `caution`이다.
- 화면은 얼굴 GIF 전체(320×240)에 하단 34 px 띠 한 줄을 얹는다. 배터리는 얼굴 화면에 없고 주행·웨이크 카드 안에만 있다. 상태 문구(띠)와 얼굴이 같은 영역을 다툰다.

### Decision

1. **한 레코드.** 순수 함수 `core_common.presentation.present(state, robot_mode, nav_state, core, screen, battery_percent)`가 `Presentation`을 낸다: `lamp`(램프 무늬), `expression`(얼굴 이름), `status_text`·`status_level`(`ok`/`caution`/`danger`), `battery_percent`·`battery_charging`(모르면 `None`, 0이 아니다), `sound`(상태 소리), `reversing`(D-546 후진음), 그리고 CORE 주의 코드를 접은 `state`. 표준 라이브러리만 쓴다. `rosy-face`는 한 틱에 이 레코드 하나로 램프를 켜고, 상태 바와 표정을 그리고, 소리를 고른다.
2. **우선순위(한 곳).** FAILED > EMERGENCY(또는 걸린 e-stop) > RECOVERING > CAUTION(건강 주의 또는 CORE 주의 코드) > BOOTING > DOCKING > BLOCKED > NAVIGATING > MANUAL > READY. D-546과 같고, 다음 둘만 다르다. **걸린 `estop`은 모드와 상관없이 `emergency`다**(화면 정지 카드와 같은 사실). **`bridge` 복구는 CAUTION에 진다**(약한 신호가 이미 바가 말하는 주의를 가리지 않는다). CORE의 1 s 값이 있으면 그것이 이기고, 없으면 파일의 값(`boot-status`)이다. CORE가 없을 때(`CORE not responding` 카드)는 램프를 파일의 10 s 모드로 두는 기존 동작을 그대로 둔다.
3. **심각도 = 램프의 심각도.** `status_level`은 이긴 램프 무늬의 심각도다: `failed`·`emergency` = danger, `recovering`·`caution`·`blocked` = caution, 나머지 = ok(`bridging`은 램프만 쓰는 약한 신호라 ok). 표정은 그 심각도가 허용하는 얼굴만 쓴다: ok는 CORE가 고른 얼굴 그대로, caution은 `basic`·`interest`·`sad`·`bored`·`angry`(밝은 얼굴 `happy`·`fun`·`hello`는 `sad`로 바뀐다), danger는 `sad`·`angry`(기본 `angry`). 램프·바 색·표정이 서로 다른 심각도를 말할 수 없다.
4. **소리.** 상태 소리(`ready`/`failed`/`caution`)와 e-stop 경보(`emergency`)는 이 레코드의 `sound`에서 온다. 상태가 바뀔 때만 울리는 규칙·caution 300 s 제한·D-546 후진음 주기는 `rosy-face`에 그대로 있다. 결과로 CORE 주의 코드와 걸린 e-stop도 이제 램프와 같은 소리를 낸다.
5. **화면 칸 나눔(320×240 가로).** 위에서부터:
   - **상태 바(0–31 px).** 왼쪽에 `status_text`(ASCII, 폰트에 한글 없음), 오른쪽에 배터리 아이콘(24×12 몸통과 마디)과 `NN%`. 충전 중이면 몸통 위에 번개, 모르면 `--`와 빈 윤곽(0 %가 아니다). 바 전체가 심각도 색이다: ok는 어두운 바탕에 잉크 글자와 아래 가는 선, caution은 주황 채움에 어두운 잉크, danger는 빨강 채움에 밝은 잉크(기존 `_draw_caution`·`_draw_alarm`과 같은 칩 어휘). 배터리 채움은 어두운 바 위에서만 `battery_color`(CRIT은 잉크로 바꿔 2.2:1 빨강을 피한다).
   - **표정 영역(32–239 px, 320×208).** GIF를 줄이지 않고 행 16–223만 잘라 놓는다(모든 GIF의 얼굴은 41–217행 안이다).
6. **카드는 어디로 가나.** 주행·웨이크 카드(D-394, 20 s마다 5 s)는 **표정 영역을 대신**한다(320×208로 그려지고 바는 그대로 위에 있다). 전체 화면 상태 카드(정지·실패·부팅·갱신·AP·로그인·CORE 응답 없음·승인 코드 D-483·종료·조명)는 사실 하나를 읽어야 하는 화면이라 **바 없이 전체 화면**이다. 대기(standby)는 화면이 잠든다. 기존 하단 띠는 없어지고 그 문구는 바의 `status_text`가 된다.
7. **호환.** `face-inputs.json` 스키마와 `screen_for`의 답은 그대로다(바는 `screen["strip"]`을 문구로 읽는다). `presentation` 모듈이 없는 릴리스(옛 `core_common`) 위의 `rosy-face`는 `face_screen`이 없을 때와 같이 얼굴 없는 상태 카드만 그리고, 램프는 단계 기반 대응표로, 소리는 그대로 돌아간다(릴리스와 `rosy-face`는 한 이미지 층으로 같이 나간다). 옛 `face-inputs`(키가 모자란 것)는 `None`으로 읽는다.

### 사용자 결정 (2026-10-09, 리뷰 뒤)

1. **소리.** CORE 주의 코드와 걸린 e-stop도 램프와 같은 소리를 낸다. 주의 소리는 5분(`BUZZER_REPEAT_S`)에 한 번만 울리도록 그대로 제한하고, 같은 제한을 `ready`에도 건다. 주의는 **약 2 s 유지된 뒤에만** 울린다(`CAUTION_DEBOUNCE_S`, 깜박이는 주의는 조용하다). 램프와 바는 즉시 바뀐다.
2. **막힘.** 경로 막힘(`blocked`)은 주황 caution으로 둔다.
3. **섞인 설치.** `presentation`이 없고 `robot_state`는 있는 릴리스에서도 램프는 CORE의 모드(EMERGENCY 포함)·복구 단계를 따르고(`robot_state.lamp_pattern`, D-546 이전 `core_common`은 세 인자 호출), 화면은 `screen_for`로 STOPPED 카드와 얼굴을 그린다. 소리와 후진음은 `rosy-face`가 레코드 `sound`·`reversing`에서 읽고, 레코드가 없을 때만 같은 필드를 옛 규칙으로 채운다(`SOUNDS` 복사본은 시험이 레코드의 것과 같음을 지킨다).

### 개정 목록 (수락 뒤 적용)

- **D-433 결정 2:** 9–11행의 "얼굴 밑 띠"를 "위쪽 상태 바"로, 12–16행의 카드가 "얼굴을 덮는다"를 "표정 영역을 대신한다"로 바꾼다. 행 번호와 우선순위는 그대로다.
- **D-546 결정 2:** 우선순위의 RECOVERING 항목에 "(`bridge`는 CAUTION보다 낮다)"를 더한다.
- **D-260 3·D-380:** 램프 무늬는 `presentation.present`가 정하고 `robot_state.lamp_pattern`은 그 안에서 쓰는 규칙표라고 적는다.

### 열린 질문

1. caution 소리(낮은음 두 번, 300 s 제한, 2 s 유지)가 현장에서 거슬리지 않는지, e-stop 해제 뒤 300 s 안에는 ready 소리가 나지 않는 것이 괜찮은지(DEVICE).
2. `CORE not responding` 카드 동안 램프를 파일의 10 s 모드로 두는 예외를 `booting`/`caution`으로 바꿀지. 부팅 때마다 CORE_READY 직후 1–2 s 동안 깜박이는 문제가 있어 지금은 두었다.
3. 주행 카드의 `⚡` 글자는 DejaVu에 없어 `CHG`로 바꿨다.
