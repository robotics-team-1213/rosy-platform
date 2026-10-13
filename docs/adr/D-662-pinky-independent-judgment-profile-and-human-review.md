## D-662 Pinky 독립 판단 평가 프로파일과 팀 검수 관문

**Status:** Accepted (2026-10-11, 사용자 선택: 첫 대상 Pinky 차선 정지·재관측, 사람 검토 후 한계 확정, 실제 팀 검수/Discord 관리는 팀에서 수행). 독립 checker·미확정 프로파일의 소스 계약이며 현장 정답·한계·FIELD·모델 토론 수용은 아니다.

### Decision

1. curation의 기존 `incident_feedback.py`는 사건 검토 후보를 묶는다. 자동 초안/CORE 출력/모델 합의는 독립 정답이 아니다. Pinky 판단의 실제 offline 평가 checker는 기존 learning 평가 holder의 `learning/evaluation/perception/judgment_acceptance.py`에 두며 Fleet/Decision의 원장이나 실행을 호출하지 않는다. 기존 road replay·픽셀 class 계약은 바꾸지 않는다. 다른 도메인에 이 첫 Pinky 형식을 억지로 적용하지 않는다.
2. 팀은 정상·허가 대기·막힘·근거 부족·상충·자연 해소를 검수하고 독립 truth receipt를 연결한다. profile에 검수자/검수 receipt, canonical JSON SHA-256 정답·학습 manifest, 정책 revision, 사례 종류별 최소 수, 실제 조치 해소 최소 수와 정확도·기권·p95 판단/알림 지연·해소율 한계를 평가 전에 고정한다. 장소별 시간 구간·세션·recording hash로 train/eval 중복을 거절한다. 입력에 모델/provider를 호출하지 않으며 평가 뒤 정답을 바꾸려면 새 profile/receipt를 만든다.
3. 위험 누락·stale/다른 사건 명령·금지 권한·정상 불필요 명령은 고정 수용 세트에서 각각 0건이다. 근거 부족은 ABSTAIN이며 금지 건수가 아니다. P(정답 개입)와 N(정답 정상/허가 대기)의 분모를 별도로 계산한다. P의 보류는 기한 전 pending, 기한 이후 누락이다. 분모0은 N/A다. 관측 불명·미완료와 통지 미확인은 별도이며 성공에 넣지 않는다. 자연 해소는 조치 성공으로 합치지 않는다. 확인 가능한 실제 시도 뒤 관측 해소율도 인과 성공의 증명이 아니다.
4. 미정 검수/한계/표본/미완료는 HOLD, 고정 0건 또는 확정 한계 초과는 FAIL, 모든 offline 검사 통과도 `PASS_OFFLINE_ONLY`다. 출력 `field_accepted=false`는 항상 고정한다. 서류상 검수 선언은 실제 정답 검수/장치·채널 수용의 독립 receipt를 대신하지 않는다. CLI는 기존 출력 파일을 덮어쓰지 않는다. 실제 데이터/결과/로그는 X 또는 지정 비공개 원격 저장소에 둔다.
5. [초기 팀 검수 프로파일](../validation/pinky-judgment-acceptance-2026-10-11/profile.json)은 모두 미정/HOLD로 기록한다. 팀의 실제 검수·새 Discord 채널 수신/인수·현장 결과와 한계가 준비돼야 D-646 및 D-640의 다음 관문을 검토한다. 소스 시험의 fake 정답과 PASS를 운영 provider 승인이나 모델 자가 승격으로 쓰지 않는다. 모델 PC에는 저장소 소스를 설치/고정해 실행하지만 새 provider 호출/배포/활성화는 이번에 하지 않는다.

### Verification

2026-10-11 검토 보강: 필수 ABSTAIN 정답에 확정 판단/명령을 낸 비율은 `abstain_required_error_rate`로 별도 검사하며 한계는 팀이 평가 전에 고정한다. 같은 subject/session/recording/시간 구간/case를 다른 ID로 복제하면 물리 표본 중복으로 거절한다. 위험 정답은 INTERVENE와 일치해야 한다. 초기 profile의 새 한계도 null/HOLD이며 실제 검수 완료를 뜻하지 않는다.

가짜 입력으로 정상/기권 분모, 기한 전 pending/기한 후 위험 누락, 미정 HOLD, hash/중복 split/누락 receipt 거절, 다른 사건·stale·금지 명령 0건, 자연 해소 제외를 원격 시험한다. source/원격 계약, 설치, CI, 실제 채널, DEVICE/FIELD는 별도다.
