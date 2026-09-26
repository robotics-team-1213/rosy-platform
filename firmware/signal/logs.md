# signal logs

추가만 한다. 형식: [module harness 설계](../docs/plans/2026-09-15-module-harness-design.md) §4.2.

## 2026-09-21 · uncommitted · feat(signal): ROSY-SIGNAL-001 계약 초안 + ESP32 참조 펌웨어
- 변경: `signal/` 신설 — `README.md`(계약 초안), `firmware/rosy_signal/rosy_signal.ino`
  (페일세이프 상태기계 참조 구현), `AGENTS.md` 3건, `progress.md`, `logs.md`,
  `test/test_signal_contract.py` 14건, 하니스 등록(`tools/harness/harness.yaml`)
- 증거: `python -m pytest test/test_signal_contract.py -q` 14 passed (2026-09-21
  Windows, Python 3.14). 부팅 모드 변이 외에 누락돼 있던 `modeName` 정의와 Wi-Fi
  SSID/키 분리를 적색 시험으로 재현한 뒤 수정했다. Arduino compile은 미실행
- gate 변화: SOURCE HOLD→GO (계약 시험 신설·통과). LOCAL/ARTIFACT/DEVICE HOLD 신설
- 결정: 없음(ADR 미작성). 설계 근거는
  `docs/plans/2026-09-21-traffic-light-controller-research.md`
- 교훈: SSR(G3MB-202P)은 AC 전용이라 접점 스위칭 용도에 부적합 — 기계식 릴레이로
  확정(조사 보고서 §4). `all_red`(점등)과 `failsafe`(점멸)의 구별이 관제 화면의
  "정지시켰다 vs 장비 고장" 판별을 만든다.

## 2026-09-22 · uncommitted · feat(signal): Fleet G-S3 클라이언트·관제 연동

- 변경: `src/site/fleet/fleet/server/signals.py` 클라이언트와 Fleet API/UI를 연결했다.
  상태 gather, 인증 command, e-stop의 병렬 `all_red`, failsafe 의도 1회 재단언을
  구현하되 로봇 CORE와 교통 안전 판정에는 연결하지 않았다.
- 증거: `python -m pytest src/site/fleet/test -q` 362 passed, 5 skipped;
  `python -m pytest test/test_signal_contract.py -q` 14 passed (2026-09-22 Windows).
- gate 변화: LOCAL HOLD→GO. ARTIFACT/DEVICE는 ESP32 빌드·물리 접점 실측 전까지 HOLD.
- 결정: 신호등은 표시 장치이며 로봇 안전 인터록이 아니라는 기존 경계를 유지한다.
- 교훈: `stale_seq`는 적용 성공이 아니며, 성공 응답도 장치가 failsafe에 남아 있으면
  재단언 예산을 다시 열면 안 된다.

## 2026-09-22 · uncommitted · docs(signal): 실물 수용 계획 — 평가 방법 고정

- 변경: `docs/plans/2026-09-22-signals-acceptance-plan.md` 신설 — 증거 등급(E1 호스트/E2 벤치/E3 현장), 수용 기준 AC-01~19(정량 합격선), 고장 주입 S-01~12, 벤치 절차 B0~B7, 구조적 약점 W1~W7. `progress.md` DEVICE blocker 가 이 계획을 가리키게 갱신
- 근거(외부): Espressif Arduino Wi-Fi API `setAutoReconnect` + 공유기 재시작 후 재접속 실패 보고(Random Nerd Tutorials "SOLVED: Reconnect ESP32 to WiFi", esp32.com) → W1. active-low 릴레이 모듈 부팅 글리치(pcbvault 트러블슈팅, HA 커뮤니티) → W2. 현재 펌웨어는 `WiFi.begin()` 1회라 W1 은 미검증 상태 — AC-12 로 실측 후 개정 여부 판단
- 증거: 문서 추가. 시험 결과 변화 없음 — `test/test_signal_contract.py` 14 passed 유지(2026-09-22 재실행)
- gate 변화: 없음(DEVICE HOLD 유지 — 이 계획이 HOLD 를 푸는 방법을 정의)
- 결정: AC-12(Ap 재시작 자기 복귀)를 FAIL 시에만 펌웨어 개정하는 절차로 둔다 — 미실측 선제 수정이 아니라 실측 → 개정 → 재시험 순서(저장소 게이트 문화)
- 교훈: "호스트 시험 통과"와 "실물 동작" 사이에는 벤치 수용 기준이라는 이름의 문서가 필요하다 — 기준을 숫자(12 s, 10회, ±2%)로 쓰지 않으면 벤치는 의견 싸움이 된다

## 2026-09-22 · uncommitted · feat(observer): 신호등 관측 서비스 — 읽기 전용 실측 평면

- 변경: `signal/observer/` 신설 — `observer.py`(HSV 색 분할 `classify_frame` + 설정 로더 + `GET /observed` FastAPI 표면 + cv2 프레임 소스), `config.example.json`, `README.md`, `AGENTS.md` 2건, 합성 프레임 시험 14건(`test/test_observer.py`), 하니스 signal 모듈에 observer 시험 등록
- 증거: `python -m pytest signal/observer/test -q` 14 passed (2026-09-22 Windows, cv2 5.0/numpy 2.5). 뮤테이션 검증: POST 경로 임시 추가 시 `test_there_is_no_command_path` 적색 확인 후 원복, 재실행 14 passed. flake8 신규 파일 클린
- gate 변화: 없음(SOURCE 유지 — 관측은 E2 벤치 실측이 앞서야 DEVICE 로 간다)
- 결정: 피드백 등급 F-EXT(외부 카메라 관측)를 1차 채택 — 토이 제품 개조 최소화. F1(내장 TCS34725)·F2(전원 MOSFET)는 벤치 후 재판정. 설계 근거 `docs/plans/2026-09-22-signal-observer-vision-design.md` §6 카메라 역할 3분리(표시 피드/속도 계측/신호 상태 관측 — 속도 1차 출처는 오도메트리, 카메라는 검증자)
- 교훈: 시험 픽스처의 cv2 좌표는 (x, y) — (y, x) 로 쓰면 "왼쪽 빨강"이 통과하고 "가운데 주황"이 실패한다. 그리고 렌즈 색을 렌더링 사진에서 추론했다가(파랑?) 실물 관찰로 정정됐다(초록·청록) — 측정이 추론을 이긴다

## 2026-09-22 · uncommitted · feat(observer): 프레임 소스 추상화 + Pi 속도 평면 설계

- 변경: `observer.py` 에 `make_source` 추상화(source=cv/file/picamera2)와 설정 검증 추가 — 같은 분류기가 Windows 벤치(cv)·Pi 현장(picamera2)·회귀 재생(file)에서 돈다. `docs/plans/2026-09-22-signal-speed-pi-design.md` 신설(Pi 배치 구조·속도 계층·AC-24~26). 운영자 지시 반영: 카메라 프롭은 속도 확인 전용(관측 마운트 재활용 철회, v2 제안·관측 설계 반영)
- 증거: `python -m pytest signal/observer/test -q` 17 passed (file 소스 순환 재생·미지 소스 거절·picamera2 부재 시 명확한 거절 포함). flake8 클린. `docs/plans/2026-09-22-signals-acceptance-plan.md` 에 AC-23(관측 카메라 적합성) 추가
- gate 변화: 없음(설계·구조 — Pi 실측은 AC-24~26 에서)
- 제안(미결정): 속도의 1차 출처는 로봇 오도메트리, Pi 카메라는 독립 검증자를 권장. 두 출처가 모일 때만 Fleet 가 과속 판정하도록(독의 2-소스 원칙 준용). 로봇 감속 메커니즘은 로봇 계약 확인 전까지 임의 경로를 만들지 않는다. **Pi 사용 여부·속도 계층은 운영자 검토 중 — 미결정**
- 교훈: 카메라는 역할이 셋이다(표시 피드/속도 계측/신호 상태 관측) — 한 스트림을 셋이 나눠 쓰게 하면 압축·지연이 계측을 오염시킨다. 소스 추상화로 "벤치에서 통과한 판정이 Pi 현장에서도 동일"을 구조로 보장한다

## 2026-09-22 · uncommitted · docs(signal): D-163 — 관측은 읽기 전용 분리 평면, 카메라 역할 셋 (ADR)

- 변경: `docs/adr/D-163-signal-observation-readonly-plane.md` 신설 + ADR Log 행 추가. `signal/progress.md` adrs 에 D-163 등재. 관측·속도 설계 문서에 ADR 참조 연결
- 내용: (1) 관측은 제어와 분리된 읽기 전용 평면(명령 경로 부재를 시험으로 고정), (2) 카메라 역할은 표시 피드/속도 계측/신호 상태 관측 셋 — 한 스트림 공유 금지, (3) 속도 1차 출처는 오도메트리, 카메라는 검증자, (4) 관측 1차는 F-EXT(비침습), 카메라 프롭 재활용 금지, (5) 색 이름을 필드로 박지 않음. Pi 배치는 미결정으로 명시
- 증거: 시험 변화 없음 — `signal/observer/test` 14 passed + `test/test_signal_contract.py` 14 passed 유지(2026-09-22)
- gate 변화: 없음
- 결정: ADR로 승격한 것은 위 5 항목뿐이다. Pi 배치·속도 계층·감속 루프·F1/F2 는 여전히 검토 중(수용 계획 AC-23~26 이 판정 절차)
- 교훈: 미결정 논의를 ADR 로 승격할 때는 "결정된 것"과 "검토 중인 것"을 ADR 안에서 분리해 적어야 한다 — 안 그러면 Proposed 로 두고 싶지도, Accepted 로 거짓말할 수도 없는 애매한 문서가 된다

## 2026-09-22 · uncommitted · feat(signal/observer): 프레임 동결 강등 + preview 자체 캡처 + ROI 경계 검증 (v0.3)

- 변경: `observer.py` — 응답에 `frame_id`·`captured_at`·`age_s`·`frozen` 추가. 내용이 `freeze_after_s`(기본 5.0 s, v2 예산 T 와 동일) 동안 안 바뀌면 frozen → `stable` 강등(`lit:null, pending, stale`) + debounce 이력 소거(동결에서 깨어나면 새로 시작). `/preview.jpeg` 가 자기 프레임을 직접 캡처(`/observed` 선행 불필요, 소스 실패 시 마지막 캡처 → 없으면 503). 설정 로더: ROI 프레임 경계 검증·frame_width/height 양수·freeze_after_s>0 거절. 버전 0.2.0 → 0.3.0.
- 변경: `config.example.json` 에 stable_after/freeze_after_s 노출, `README.md` 응답 스키마·preview·설정 문서 갱신, `AGENTS.md` 시험 수 14→32.
- 증거: `python -m pytest signal/observer/test -q` → 32 passed (신규 9건: 동결 강등·해제 debounce 재시작·frame_id/age·preview 자체 캡처·설정 거절 5종). flake8 대상 파일 무결 (2026-09-22 Windows).
- gate 변화: 없음 — 합성 ≠ DEVICE, 실촬 회귀·AC-23/24 는 벤치(B0~B7) 몫.
- 교훈: 멈춘 프레임의 CONFIRMED 는 가장 비싼 거짓말이다 — 정보의 나이(frame_id/age)를 응답에 실어 소비자가 스스로 강등하게 하는 편이, 서버가 "지금 켜짐"을 조작하는 것보다 낫다.

## 2026-09-25 · uncommitted · refactor(firmware): move signal under firmware/ (D-231)

- 변경: `firmware/signal/`로 이동, 동작 변경 없음 (D-231)
- 증거: 이 커밋의 신호 계약 시험과 observer 시험
- gate 변화: 없음
- 결정: D-231
- 교훈: 없음
